"""Ears — microphone capture with RMS silence detection + faster-whisper,
tuned for Hindi and English (fully local, no audio leaves the Mac).

Language handling:
  * Whisper detects the language per utterance, but we only allow Hindi or
    English. Hindi speech is often mis-detected as Urdu (same spoken language,
    different script) — that probability is folded into Hindi so you get
    Devanagari text, not Urdu script.
  * JARVIS_LANGUAGE=hi / en forces one language if detection misbehaves.
"""
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass

import numpy as np

from . import config

log = logging.getLogger("jarvis.listen")

WAKE_VARIANTS = (
    "friday", "fryday", "fry day", "fri day", "fraiday", "freyday", "fridae",
    "frida", "fridy", "fridai", "freida", "fraidy",   # common mishearings by the English-only wake gate
    "फ्राइडे", "फ्राईडे", "फ्रायडे", "फ्राइडै", "फ्राइ डे", "फ्रेडे",
    "فرائیڈے", "فرائڈے", "فرائیڈی",
)
# "Friday" is also a weekday ("remind me on Friday"), so the wake word only counts
# at the START of an utterance ("Friday, open Chrome" / "Hey Friday ...") or as a
# comma-separated tail ("Open Chrome, Friday"), never in the middle of a sentence.
_NAMES = "|".join(re.escape(v) for v in sorted(WAKE_VARIANTS, key=len, reverse=True))
_GREET = r"(?:(?:hey|hi|hello|ok|okay|हे|हेलो|ओके)[\s,]+)?"
# Devanagari letters, but NOT the danda "।" (U+0964/0965): "फ्राइडे। क्रोम खोलो" must still wake.
_WORD_END = r"(?![\w\u0900-\u0963\u0966-\u097F\u0600-\u06FF])"
_START_RE = re.compile(r"^[\s,.]*" + _GREET + r"(?:" + _NAMES + r")" + _WORD_END + r"[\s,.!?।]*", re.I)
_END_RE = re.compile(r",\s*(?:" + _NAMES + r")[\s.!?।]*$", re.I)

# Vocabulary hints only. Whisper tends to echo its prompt when it hears noise, so the
# prompt must never be something a user could plausibly say (it used to be real commands).
PROMPTS = {
    "hi": "फ्राइडे। क्रोम, सफारी, स्पॉटिफाई, यूट्यूब, व्हाट्सएप, वॉल्यूम, बैटरी, स्क्रीनशॉट।",
    "en": "Friday. Chrome, Safari, Spotify, YouTube, WhatsApp, volume, battery, screenshot.",
}
_PROMPT_WORDS = {w for p in PROMPTS.values() for w in re.findall(r"[\w\u0900-\u097F]+", p.lower())}


@dataclass
class Heard:
    text: str
    lang: str  # "hi" | "en"


def contains_wake_word(text: str) -> bool:
    text = text or ""
    return bool(_START_RE.match(text) or _END_RE.search(text))


def strip_wake_word(text: str) -> str:
    text = text or ""
    if _START_RE.match(text):
        text = _START_RE.sub("", text, count=1)
    else:
        text = _END_RE.sub("", text, count=1)
    return text.strip(" ,.!?।")


class AdaptiveThreshold:
    """Speech threshold that follows the room: ~3x the ambient noise floor, never
    below the configured SILENCE_THRESHOLD. The floor drops fast (quiet moment) and
    rises slowly (so speech doesn't drag it up)."""

    def __init__(self, base: float, factor: float = 3.0, ceiling: float = 0.08):
        self.base, self.factor, self.ceiling = base, factor, ceiling
        self.floor: float | None = None

    def update(self, rms: float) -> None:
        if self.floor is None:
            self.floor = rms
        elif rms < self.floor:
            self.floor = 0.8 * self.floor + 0.2 * rms
        else:
            self.floor = 0.995 * self.floor + 0.005 * rms

    @property
    def value(self) -> float:
        if self.floor is None:
            return self.base
        return min(self.ceiling, max(self.base, self.floor * self.factor))


def clean_audio(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Remove rumble/DC below 80 Hz and bring quiet speech up to a healthy level.
    Only call this on audio that already passed the speech gate — amplifying pure
    noise would invite hallucinations."""
    if audio.size < 1024:
        return audio
    spec = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(audio.size, 1.0 / sr)
    spec[freqs < 80] = 0
    out = np.fft.irfft(spec, n=audio.size).astype(np.float32)
    peak = float(np.max(np.abs(out)))
    if 1e-4 < peak < 0.5:
        out *= min(0.6 / peak, 20.0)         # at most +26 dB
    return out


def segment_ok(seg) -> bool:
    """Whisper's own confidence signals. Drops segments that are probably not speech
    or are a decoding loop."""
    if getattr(seg, "no_speech_prob", 0.0) > 0.6 and getattr(seg, "avg_logprob", 0.0) < -1.0:
        return False
    if getattr(seg, "avg_logprob", 0.0) < -1.6:
        return False
    if getattr(seg, "compression_ratio", 0.0) > 2.4:
        return False
    return True


def _has_speech(audio: np.ndarray) -> bool:
    """Silero VAD (bundled with faster-whisper, ~3 ms): is there any speech at all? Lets the
    always-on loop skip noise bursts without running Whisper on them."""
    try:
        from faster_whisper.vad import get_speech_timestamps
        return bool(get_speech_timestamps(audio))
    except Exception:       # VAD unavailable: let Whisper decide
        return True


class Ears:
    def __init__(self, level_callback=None):
        self._model = None
        self._model_lock = threading.Lock()
        self.level_callback = level_callback  # called with RMS while recording
        self.stop_event = threading.Event()
        self.threshold = AdaptiveThreshold(config.SILENCE_THRESHOLD)

    # ---------- model ----------
    def load(self):
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                log.info("loading Whisper model '%s'...", config.WHISPER_MODEL)
                self._model = WhisperModel(config.WHISPER_MODEL, device="cpu",
                                           compute_type=config.WHISPER_COMPUTE,
                                           cpu_threads=config.WHISPER_THREADS)
        return self._model

    # ---------- recording ----------
    def record(self, max_wait_for_speech: float | None = None) -> np.ndarray | None:
        """Record until the speaker goes quiet. Returns float32 mono audio, or
        None if nobody spoke within max_wait_for_speech seconds / cancelled."""
        import sounddevice as sd

        self.stop_event.clear()
        sr = config.SAMPLE_RATE
        block = int(sr * 0.05)  # 50 ms
        q: "queue.Queue[np.ndarray]" = queue.Queue()

        def cb(indata, _frames, _time, status):
            if status:
                log.debug("audio status: %s", status)
            q.put(indata[:, 0].copy())

        frames, started, silent_for, voiced = [], False, 0.0, 0
        thr = config.SILENCE_THRESHOLD
        pre_roll: list[np.ndarray] = []  # keep 300 ms before speech starts
        t0 = time.time()
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32", blocksize=block,
                            device=config.MIC_DEVICE, callback=cb):
            while not self.stop_event.is_set():
                try:
                    chunk = q.get(timeout=0.5)
                except queue.Empty:    # the mic stalled: still honour the wait limit
                    if not started and max_wait_for_speech and time.time() - t0 > max_wait_for_speech:
                        return None
                    continue
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                if self.level_callback:
                    try:
                        self.level_callback(rms)
                    except Exception:
                        pass
                if not started:
                    thr = self.threshold.value if config.ADAPTIVE_NOISE else config.SILENCE_THRESHOLD
                    pre_roll = (pre_roll + [chunk])[-6:]
                    if rms > thr:
                        started = True
                        frames.extend(pre_roll)
                        voiced += 1
                    else:
                        self.threshold.update(rms)       # learn the room while nobody speaks
                        if max_wait_for_speech and time.time() - t0 > max_wait_for_speech:
                            return None
                    continue
                frames.append(chunk)
                if rms >= thr:
                    voiced += 1
                silent_for = silent_for + 0.05 if rms < thr else 0.0
                if silent_for >= config.SILENCE_DURATION:
                    break
                if len(frames) * 0.05 > config.MAX_RECORD_SECONDS:
                    break
        if self.stop_event.is_set() or not frames:
            return None
        audio = np.concatenate(frames)
        if len(audio) < sr * 0.3 or voiced * 0.05 < config.MIN_SPEECH_SECONDS:
            # a click, cough or door slam -- or very quiet speech. Levels only, never words.
            log.info("ignored %.1fs of sound: only %.2fs above the speech threshold %.4f (peak %.4f)",
                     len(audio) / sr, voiced * 0.05, thr, float(np.max(np.abs(audio))))
            return None
        return audio

    # ---------- transcription ----------
    def transcribe(self, audio: np.ndarray, force_lang: str | None = None) -> Heard:
        model = self.load()
        lang = force_lang or (config.LANGUAGE_MODE if config.LANGUAGE_MODE in ("hi", "en") else None)
        if lang is None:
            lang = self._detect(model, audio)
        return Heard(text=self._decode(model, audio, lang, beam_size=5), lang=lang)

    @staticmethod
    def _decode(model, audio, lang: str, beam_size: int, use_prompt: bool = True) -> str:
        segments, _info = model.transcribe(
            audio, language=lang, beam_size=beam_size, vad_filter=True,
            initial_prompt=PROMPTS[lang] if use_prompt else None, condition_on_previous_text=False,
            temperature=0.0,                 # no "creative" retries on unclear audio
            # We only use the text. Timestamp decoding made Hindi (multi-byte tokens) take 5-10 s
            # instead of ~2 s, and made Whisper loop on its vocabulary prompt.
            without_timestamps=True,
            no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4,
        )
        kept, dropped = [], 0
        for seg in segments:
            if segment_ok(seg):
                kept.append(seg.text.strip())
            else:
                dropped += 1
                log.debug("dropped low-confidence segment %r (no_speech=%.2f logprob=%.2f)",
                          seg.text, seg.no_speech_prob, seg.avg_logprob)
        if not kept and dropped and use_prompt:
            # Speech was detected but Whisper looped on its own vocabulary prompt (typical for
            # quiet audio). Try once more without the prompt before giving up.
            return Ears._decode(model, audio, lang, beam_size, use_prompt=False)
        return " ".join(kept).strip()

    @staticmethod
    def _detect(model, audio) -> str:
        """Pick 'hi' or 'en' — Urdu/Punjabi/etc. probability counts as Hindi.
        detect_language() runs one encoder pass (~0.7 s); the old approach decoded
        the whole clip with no language set, which took 1-12 s."""
        try:
            _lang, _p, all_probs = model.detect_language(audio[: config.SAMPLE_RATE * 30])
            probs = dict(all_probs or [])
        except Exception as e:
            log.debug("language detection failed: %s", e)
            return "en"
        hindi_like = sum(probs.get(k, 0.0) for k in ("hi", "ur", "pa", "mr", "ne", "bn", "gu"))
        english = probs.get("en", 0.0)
        return "hi" if hindi_like > english else "en"

    def _wake_gate(self, model, audio, t0: float) -> "Heard | None":
        """Cheap check for the always-on loop. A greedy English pass catches "Friday ..." in
        English; if that misses (a Hindi "फ्राइडे" is often garbled by the English decoder) and the
        audio is Hindi, try Hindi before giving up. Returns the Heard to act on, or None."""
        quick = self._decode(model, audio, "en", beam_size=1)
        if quick and not _is_hallucination(quick) and contains_wake_word(quick):
            lang = self._detect(model, audio)
            return Heard(text=quick, lang="en") if lang == "en" else self.transcribe(audio, force_lang=lang)
        heard = None
        if self._detect(model, audio) == "hi":
            heard = self.transcribe(audio, force_lang="hi")
            if not heard.text or _is_hallucination(heard.text) or not contains_wake_word(heard.text):
                heard = None
        if heard is None:
            # INFO so "it didn't hear me" can be diagnosed from the log (text only if allowed)
            log.info("wake gate: no wake word (%.1fs of audio, %.2fs)%s", len(audio) / config.SAMPLE_RATE,
                     time.time() - t0, f": {quick!r}" if config.LOG_TRANSCRIPTS else "")
        return heard

    def listen(self, max_wait_for_speech: float | None = None,
               force_lang: str | None = None, wake_gate: bool = False) -> Heard | None:
        """Record one utterance and transcribe it.

        wake_gate=True is for the always-on "waiting for Friday" loop: clips with no
        speech (VAD) are dropped for free; the rest get a quick greedy English pass
        (plus a Hindi pass if the audio is Hindi) and are dropped unless they start
        with the wake word. Only a real wake-up pays for the full transcription."""
        audio = self.record(max_wait_for_speech)
        if audio is None:
            return None
        audio = clean_audio(audio, config.SAMPLE_RATE)
        t0 = time.time()
        if wake_gate:
            model = self.load()
            if not _has_speech(audio):
                log.debug("wake gate: no speech in %.1fs of audio", len(audio) / config.SAMPLE_RATE)
                return None
            heard = self._wake_gate(model, audio, t0)
            if heard is None:
                return None
        else:
            heard = self.transcribe(audio, force_lang)
        log.info("heard (%s) in %.2fs%s", heard.lang, time.time() - t0,
                 f": {heard.text}" if config.LOG_TRANSCRIPTS else "")
        if not heard.text or _is_hallucination(heard.text):
            return None
        return heard


# Whisper famously "hears" these in silence/noise (learned from YouTube captions).
_HALLUCINATIONS = {
    "thank you for watching", "thanks for watching", "thank you", "thanks", "you", "bye", "bye bye",
    "please subscribe", "like and subscribe", "see you next time", "see you in the next video",
    "धन्यवाद", "शुक्रिया", "आपका धन्यवाद", "हम्म", "हम्", "अच्छा",
}
_HALLUCINATION_PARTS = ("subscribe", "सब्सक्राइब", "amara.org", "subtitles by", "subtitled by",
                        "captions by", "www.", ".com/", "सबटाइटल")
_LETTERS = re.compile(r"[A-Za-z\u0900-\u097F]")
_BRACKETED = re.compile(r"^\s*[\[\(♪♫*].*[\]\)♪♫*]?\s*$")


def _is_loop(text: str) -> bool:
    """'the the the the', 'हाँ हाँ हाँ हाँ' or a bigram repeated 4+ times: a decoding loop."""
    words = text.lower().split()
    if len(words) >= 5 and len(set(words)) / len(words) < 0.35:
        return True
    bigrams = list(zip(words, words[1:]))
    return len(bigrams) >= 4 and max(bigrams.count(b) for b in set(bigrams)) >= 4


def _echoes_prompt(text: str) -> bool:
    """Whisper repeating its vocabulary prompt back ('Chrome, Safari, Spotify...')."""
    words = re.findall(r"[\w\u0900-\u097F]+", text.lower())
    return len(words) >= 3 and len(set(words)) >= 3 and all(w in _PROMPT_WORDS for w in words)


def _is_hallucination(text: str) -> bool:
    t = (text or "").strip().lower().strip(".!?। ,")
    if len(t) < 2 or t in _HALLUCINATIONS:
        return True
    if any(part in t for part in _HALLUCINATION_PARTS):
        return True
    if not _LETTERS.search(t):                      # only symbols / CJK / Cyrillic: not our languages
        return True
    if _BRACKETED.match(t) and ("music" in t or "applause" in t or "laughter" in t or "संगीत" in t or "♪" in t):
        return True
    return _is_loop(t) or _echoes_prompt(t)
