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
    "फ्राइडे", "फ्राईडे", "फ्रायडे", "फ्राइडै", "फ्राइ डे", "फ्रेडे",
    "فرائیڈے", "فرائڈے", "فرائیڈی",
)
# "Friday" is also a weekday ("remind me on Friday"), so the wake word only counts
# at the START of an utterance ("Friday, open Chrome" / "Hey Friday ...") or as a
# comma-separated tail ("Open Chrome, Friday"), never in the middle of a sentence.
_NAMES = "|".join(re.escape(v) for v in sorted(WAKE_VARIANTS, key=len, reverse=True))
_GREET = r"(?:(?:hey|hi|hello|ok|okay|हे|हेलो|ओके)[\s,]+)?"
_WORD_END = r"(?![\w\u0900-\u097F\u0600-\u06FF])"
_START_RE = re.compile(r"^[\s,.]*" + _GREET + r"(?:" + _NAMES + r")" + _WORD_END + r"[\s,.!?।]*", re.I)
_END_RE = re.compile(r",\s*(?:" + _NAMES + r")[\s.!?।]*$", re.I)

PROMPTS = {
    "hi": "फ्राइडे, क्रोम खोलो। आज मौसम कैसा है? वॉल्यूम कम करो।",
    "en": "Friday, open Chrome. What's the time? Turn the volume down.",
}


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


class Ears:
    def __init__(self, level_callback=None):
        self._model = None
        self._model_lock = threading.Lock()
        self.level_callback = level_callback  # called with RMS while recording
        self.stop_event = threading.Event()

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

        frames, started, silent_for = [], False, 0.0
        pre_roll: list[np.ndarray] = []  # keep 300 ms before speech starts
        t0 = time.time()
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32", blocksize=block,
                            device=config.MIC_DEVICE, callback=cb):
            while not self.stop_event.is_set():
                try:
                    chunk = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                if self.level_callback:
                    try:
                        self.level_callback(rms)
                    except Exception:
                        pass
                if not started:
                    pre_roll = (pre_roll + [chunk])[-6:]
                    if rms > config.SILENCE_THRESHOLD:
                        started = True
                        frames.extend(pre_roll)
                    elif max_wait_for_speech and time.time() - t0 > max_wait_for_speech:
                        return None
                    continue
                frames.append(chunk)
                silent_for = silent_for + 0.05 if rms < config.SILENCE_THRESHOLD else 0.0
                if silent_for >= config.SILENCE_DURATION:
                    break
                if len(frames) * 0.05 > config.MAX_RECORD_SECONDS:
                    break
        if self.stop_event.is_set() or not frames:
            return None
        audio = np.concatenate(frames)
        if len(audio) < sr * 0.3:  # < 300 ms: a click or cough
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
    def _decode(model, audio, lang: str, beam_size: int) -> str:
        segments, _info = model.transcribe(
            audio, language=lang, beam_size=beam_size, vad_filter=True,
            initial_prompt=PROMPTS[lang], condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()

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

    def listen(self, max_wait_for_speech: float | None = None,
               force_lang: str | None = None, wake_gate: bool = False) -> Heard | None:
        """Record one utterance and transcribe it.

        wake_gate=True is for the always-on "waiting for Friday" loop: every
        noise burst gets a quick English-only pass (no language detection, greedy
        decoding) and is dropped unless it starts with the wake word. Only a real
        wake-up pays for language detection / a Hindi re-transcription."""
        audio = self.record(max_wait_for_speech)
        if audio is None:
            return None
        t0 = time.time()
        if wake_gate:
            model = self.load()
            quick = self._decode(model, audio, "en", beam_size=1)
            if not quick or _is_hallucination(quick) or not contains_wake_word(quick):
                log.debug("wake gate: no wake word in %r (%.2fs)", quick, time.time() - t0)
                return None
            lang = self._detect(model, audio)
            heard = Heard(text=quick, lang="en") if lang == "en" else self.transcribe(audio, force_lang=lang)
        else:
            heard = self.transcribe(audio, force_lang)
        log.info("heard (%s) in %.2fs: %s", heard.lang, time.time() - t0, heard.text)
        if not heard.text or _is_hallucination(heard.text):
            return None
        return heard


# Whisper famously "hears" these in silence/noise.
_HALLUCINATIONS = (
    "thank you for watching", "thanks for watching", "you", "...",
)


def _is_hallucination(text: str) -> bool:
    t = text.strip().lower().strip(".!?। ")
    return len(t) < 2 or t in _HALLUCINATIONS or "subscribe" in t or "सब्सक्राइब" in t
