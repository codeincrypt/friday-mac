"""All Friday settings, loaded from .env (project root) and
~/Library/Application Support/Friday/.env (per-user overrides)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional at import time (tests)
    def load_dotenv(*_a, **_k):
        return False

ROOT = Path(__file__).resolve().parent.parent
SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Friday"
CACHE_DIR = SUPPORT_DIR / "voice-cache"
LOG_FILE = SUPPORT_DIR / "friday.log"


def _migrate_legacy_support_dir() -> None:
    """The app used to be called Jarvis: carry over its settings, logs and voice
    cache so a rename doesn't lose them. Never overwrites anything in the new dir."""
    old = SUPPORT_DIR.parent / "Jarvis"
    try:
        if not old.is_dir():
            return
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        for item in old.iterdir():
            target = SUPPORT_DIR / ("friday.log" if item.name == "jarvis.log" else item.name)
            if not target.exists():
                item.rename(target)
    except OSError:
        pass  # best effort; a fresh Friday folder is created on demand


_migrate_legacy_support_dir()

load_dotenv(ROOT / ".env")
load_dotenv(SUPPORT_DIR / ".env", override=True)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


ASSISTANT_NAME = os.getenv("JARVIS_NAME", "Friday")
USER_TITLE_EN = os.getenv("JARVIS_USER_TITLE_EN", "sir")
USER_TITLE_HI = os.getenv("JARVIS_USER_TITLE_HI", "सर")

# ---- Brain: local model via Ollama (fully offline) ----
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_HOST.startswith("http"):
    OLLAMA_HOST = "http://" + OLLAMA_HOST
LOCAL_MODEL = os.getenv("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
LLM_TIMEOUT = _float("JARVIS_LLM_TIMEOUT", 90)
TEMPERATURE = _float("JARVIS_TEMPERATURE", 0.2)   # low = fewer invented facts and more reliable tool calls
MAX_HISTORY_TURNS = int(_float("JARVIS_MAX_HISTORY", 8))
NUM_CTX = int(_float("JARVIS_NUM_CTX", 16384))   # 27 tool schemas + system prompt use ~3k of this

# ---- Ears: faster-whisper (local) ----
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # small handles Hindi far better than base
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_THREADS = int(_float("WHISPER_THREADS", min(8, os.cpu_count() or 4)))  # CPU threads for Whisper
# auto = detect Hindi/English per utterance; or force "hi" / "en"
LANGUAGE_MODE = os.getenv("JARVIS_LANGUAGE", "auto").lower()
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = _float("SILENCE_THRESHOLD", 0.008)
SILENCE_DURATION = _float("SILENCE_DURATION", 0.7)
MAX_RECORD_SECONDS = _float("MAX_RECORD_SECONDS", 15)
CONVERSATION_TIMEOUT = _float("CONVERSATION_TIMEOUT", 8)
ADAPTIVE_NOISE = _bool("JARVIS_ADAPTIVE_NOISE", True)        # threshold follows the room's noise floor
MIN_SPEECH_SECONDS = _float("MIN_SPEECH_SECONDS", 0.15)       # less voiced audio than this = a click, ignored
POST_SPEAK_PAUSE = _float("POST_SPEAK_PAUSE", 0.3)            # let the room go quiet before listening again
MIC_DEVICE = os.getenv("MIC_DEVICE") or None
if MIC_DEVICE is not None and MIC_DEVICE.isdigit():
    MIC_DEVICE = int(MIC_DEVICE)
WAKE_WORD_ENABLED = _bool("JARVIS_WAKE_WORD", True)

# ---- Mouth: neural voices (edge-tts) with macOS `say` fallback ----
TTS_ENGINE = os.getenv("JARVIS_TTS", "neural")  # neural | say
VOICE_EN = os.getenv("JARVIS_VOICE_EN", "en-GB-RyanNeural")   # British male, crisp
VOICE_HI = os.getenv("JARVIS_VOICE_HI", "hi-IN-MadhurNeural")  # Hindi male
VOICE_RATE = os.getenv("JARVIS_VOICE_RATE", "+4%")
VOICE_PITCH = os.getenv("JARVIS_VOICE_PITCH", "-4Hz")
SAY_VOICE_EN = os.getenv("JARVIS_SAY_VOICE_EN", "Daniel")
SAY_VOICE_HI = os.getenv("JARVIS_SAY_VOICE_HI", "Lekha")
SAY_RATE = int(_float("JARVIS_SAY_RATE", 185))

CACHE_MAX_MB = _float("JARVIS_CACHE_MAX_MB", 50)   # voice-cache size cap; oldest clips are pruned

# ---- Behaviour ----
SAFE_MODE = _bool("JARVIS_SAFE_MODE", True)
HOTKEY = os.getenv("JARVIS_HOTKEY", "option+j")
# Transcripts can contain email text, passwords read aloud, etc. Off = log only timings/languages.
LOG_TRANSCRIPTS = _bool("JARVIS_LOG_TRANSCRIPTS", False)

for d in (SUPPORT_DIR, CACHE_DIR):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
