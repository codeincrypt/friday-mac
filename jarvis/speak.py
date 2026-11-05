"""Mouth — neural voices (Microsoft edge-tts) with a macOS `say` fallback.

English  -> en-GB-RyanNeural   (British male, crisp, butler-like)
Hindi    -> hi-IN-MadhurNeural (Hindi male)

Neural speech needs internet; when it's unavailable Friday silently falls
back to the offline macOS voices so it never goes mute. Every clip is cached
on disk, so repeated phrases ("Yes, sir?") play instantly and work offline.
"""
import asyncio
import hashlib
import logging
import re
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .lang import detect_language

log = logging.getLogger("jarvis.speak")

_MD = re.compile(r"[*_`#>|]+|\[(.*?)\]\(.*?\)")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")


def clean_for_speech(text: str) -> str:
    text = _MD.sub(lambda m: m.group(1) or "", text or "")
    text = _EMOJI.sub("", text)
    text = re.sub(r"https?://\S+", "the link", text)
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


def split_sentences(text: str, min_len: int = 28, max_chunks: int = 4) -> list[str]:
    """Break a reply into a few speakable chunks. Tiny fragments ("Sir.") are
    merged into their neighbour so playback doesn't sound choppy."""
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    chunks: list[str] = []
    for part in parts:
        if chunks and len(chunks[-1]) < min_len:
            chunks[-1] += " " + part
        else:
            chunks.append(part)
    while len(chunks) > max_chunks:  # very long replies: fold the tail together
        chunks[-2] += " " + chunks.pop()
    return chunks or [text]


class Speaker:
    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self._neural_down_until = 0.0
        self.cancelled = False
        try:
            import edge_tts  # noqa: F401
            self._edge_ok = True
        except ImportError:
            self._edge_ok = False
            log.warning("edge-tts not installed — using macOS say")

    # ---------- public ----------
    def speak(self, text: str, lang: str | None = None) -> None:
        """Speak and block until finished (or stop() is called)."""
        text = clean_for_speech(text)
        if not text:
            return
        lang = lang or detect_language(text)
        self.cancelled = False
        if sys.stdout.isatty():  # terminal debugging only; never into launch.log
            print(f"🤖 {config.ASSISTANT_NAME}: {text}")
        if config.TTS_ENGINE == "neural" and self._edge_ok and time.time() > self._neural_down_until:
            self._speak_pipelined(text, lang)
        else:
            self._say(text, lang)
        if not self.cancelled:
            time.sleep(config.POST_SPEAK_PAUSE)   # don't let the mic catch our own voice tail / reverb

    def _speak_pipelined(self, text: str, lang: str) -> None:
        """Synthesise every sentence at once and play them in order as they
        finish, so speech starts after the FIRST sentence is ready (~1-2 s)
        instead of after the whole reply has been rendered."""
        chunks = split_sentences(text)
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            futures = [pool.submit(self._neural_clip, c, lang) for c in chunks]
            for chunk, fut in zip(chunks, futures):
                if self.cancelled:
                    break
                path = fut.result()
                if self.cancelled:
                    break
                if path:
                    self._play(["afplay", str(path)])
                else:
                    self._say(chunk, lang)  # neural unavailable -> macOS voice for this bit

    def stop(self) -> None:
        self.cancelled = True
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def precache(self, items, progress=None) -> bool:
        """Render fixed phrases so they play instantly (4 at a time).
        progress(done, total) is called as clips finish. Returns False if the
        neural voice was unreachable (offline), True otherwise."""
        items = list(items)
        if not (config.TTS_ENGINE == "neural" and self._edge_ok):
            return False

        def one(item):
            lang, text = item
            if time.time() < self._neural_down_until:
                return False
            return self._neural_clip(clean_for_speech(text), lang) is not None

        ok_all, done = True, 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for ok in pool.map(one, items):
                ok_all = ok_all and ok
                done += 1
                if progress:
                    progress(done, len(items))
        return ok_all

    # ---------- internals ----------
    def _voice(self, lang: str) -> str:
        return config.VOICE_HI if lang == "hi" else config.VOICE_EN

    def _cache_path(self, text: str, voice: str) -> Path:
        key = f"{voice}|{config.VOICE_RATE}|{config.VOICE_PITCH}|{text}"
        return config.CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".mp3")

    def _neural_clip(self, text: str, lang: str):
        voice = self._voice(lang)
        path = self._cache_path(text, voice)
        if path.exists() and path.stat().st_size > 0:
            try:
                os.utime(path)  # recently used = keep when pruning
            except OSError:
                pass
            return path
        try:
            import edge_tts

            async def _render():
                comm = edge_tts.Communicate(text, voice, rate=config.VOICE_RATE,
                                            pitch=config.VOICE_PITCH)
                await comm.save(str(path) + ".part")

            asyncio.run(asyncio.wait_for(_render(), timeout=10))
            Path(str(path) + ".part").rename(path)
            return path
        except Exception as e:  # offline, DNS, service hiccup...
            log.info("neural TTS unavailable (%s) — falling back to say", e)
            Path(str(path) + ".part").unlink(missing_ok=True)
            self._neural_down_until = time.time() + 60  # retry in a minute
            return None

    def _say(self, text: str, lang: str) -> None:
        voice = config.SAY_VOICE_HI if lang == "hi" else config.SAY_VOICE_EN
        rc = self._play(["say", "-v", voice, "-r", str(config.SAY_RATE), text])
        if rc not in (0, None) and not self.cancelled:
            self._play(["say", text])  # voice not installed -> system default

    def _play(self, cmd) -> int | None:
        try:
            with self._lock:
                self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
            return self._proc.wait()
        except FileNotFoundError:
            log.error("%s not found (not running on macOS?)", cmd[0])
            return None


def prune_cache(max_mb: float | None = None) -> int:
    """Delete the least-recently-used clips until the cache fits. Returns bytes freed."""
    limit = int((config.CACHE_MAX_MB if max_mb is None else max_mb) * 1024 * 1024)
    try:
        files = []
        for f in config.CACHE_DIR.iterdir():
            if f.suffix == ".part":
                f.unlink(missing_ok=True)   # leftovers from an interrupted download
            elif f.suffix == ".mp3":
                st = f.stat()
                files.append((st.st_mtime, st.st_size, f))
        total, freed = sum(sz for _, sz, _ in files), 0
        for _mtime, size, f in sorted(files):
            if total <= limit:
                break
            f.unlink(missing_ok=True)
            total -= size
            freed += size
        return freed
    except OSError as e:
        log.debug("cache prune failed: %s", e)
        return 0


_speaker = Speaker()


def speak(text: str, lang: str | None = None) -> None:
    _speaker.speak(text, lang)


def stop_speaking() -> None:
    _speaker.stop()


def precache(items) -> None:
    def work(batch):
        _speaker.precache(batch)   # touches the fixed phrases, so they count as "recent"...
        prune_cache()              # ...and survive the size cap

    threading.Thread(target=work, args=(list(items),), daemon=True).start()
