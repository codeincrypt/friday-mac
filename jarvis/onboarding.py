"""First-run setup — takes a fresh Mac from "Friday.app is installed" to a working
offline assistant, with progress the setup window (jarvis/ui/setup.html) can show.

Steps (in order):
  engine  install + start Ollama (the local AI engine)
  brain   download the language model (qwen2.5, picked for this Mac's RAM)
  ears    download the Whisper speech model
  voice   render Friday's fixed voice lines          (optional, needs internet)
  mic     microphone permission                       (optional)
  access  Accessibility permission (typing/keys)      (optional)

UI-agnostic: nothing here imports pywebview/AppKit, so it is unit-tested on any OS.
Every step first checks whether its work is already done, so re-running is cheap.
"""
import ctypes
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from . import config

log = logging.getLogger("jarvis.setup")

SETUP_VERSION = 1

# Ollama's official macOS download (a universal .app inside a zip) and manual page.
OLLAMA_ZIP_URL = "https://ollama.com/download/Ollama-darwin.zip"
OLLAMA_PAGE = "https://ollama.com/download"
_SETTINGS_PREFIX = "x-apple.systempreferences:com.apple.preference.security?Privacy_"
_ALLOWED_URLS = (OLLAMA_PAGE,)

# id, English title, Hindi subtitle, optional?
STEPS = [
    ("engine", "Local AI engine", "लोकल AI इंजन", False),
    ("brain", "Friday's brain", "फ्राइडे का दिमाग़", False),
    ("ears", "Speech recognition", "आवाज़ पहचान", False),
    ("voice", "Friday's voice", "फ्राइडे की आवाज़", True),
    ("mic", "Microphone access", "माइक्रोफ़ोन की अनुमति", True),
    ("access", "Accessibility access", "टाइपिंग व कीज़ की अनुमति", True),
]
_ORDER = [s[0] for s in STEPS]

# Language models: Hindi + reliable tool calling is why this is the qwen2.5 family.
MODELS = [
    {"id": "qwen2.5:3b", "label": "Light", "size_gb": 1.9,
     "note": "Fastest, weaker Hindi. For 8 GB Macs."},
    {"id": "qwen2.5:7b", "label": "Balanced", "size_gb": 4.7,
     "note": "Good Hindi and dependable tools. Best for 16 GB."},
    {"id": "qwen2.5:14b", "label": "Best", "size_gb": 9.0,
     "note": "Best Hindi and reasoning. Needs 32 GB or more."},
]
# Approximate download sizes (MB) of the Whisper models, used for the progress bar.
_WHISPER_MB = {"tiny": 75, "base": 145, "small": 484, "medium": 1530, "large-v3": 3100}
_OLLAMA_APP_GB = 0.6


class SetupError(Exception):
    def __init__(self, message: str, hint: str = "", actions=None):
        super().__init__(message)
        self.hint = hint
        self.actions = actions or []


class _Cancelled(Exception):
    pass


class _Skipped(Exception):
    pass


# ======================= machine facts & choices =======================
def ram_gb() -> int:
    try:
        return round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30)
    except (ValueError, OSError, AttributeError):
        return 8


def free_gb(path: Path | None = None) -> float:
    try:
        return round(shutil.disk_usage(path or Path.home()).free / 2**30, 1)
    except OSError:
        return 0.0


def chip_name() -> str:
    try:
        out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                             text=True, timeout=3).stdout.strip()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.machine()


def hardware() -> dict:
    return {"ram_gb": ram_gb(), "free_gb": free_gb(), "arch": platform.machine(), "chip": chip_name()}


def recommend_model(ram: int) -> str:
    if ram < 12:
        return "qwen2.5:3b"
    return "qwen2.5:14b" if ram >= 32 else "qwen2.5:7b"


def num_ctx_for(ram: int) -> int:
    return 8192 if ram < 16 else 16384   # the context window costs ~1 GB of RAM at 16k


def model_size_gb(model: str) -> float:
    for m in MODELS:
        if m["id"] == model:
            return m["size_gb"]
    return 5.0   # a custom model from .env: assume a typical 7B download


def whisper_mb(size: str) -> int | None:
    return _WHISPER_MB.get(size)


# ======================= persisted state =======================
def _marker() -> Path:
    return config.SUPPORT_DIR / "setup.json"


def _env_file() -> Path:
    return config.SUPPORT_DIR / ".env"


def needs_setup() -> bool:
    """True until a setup run has finished on this Mac (the marker lives in the
    per-user support folder, so a copied project folder never skips it)."""
    if os.getenv("FRIDAY_SKIP_SETUP") == "1":
        return False
    if os.getenv("FRIDAY_FORCE_SETUP") == "1":
        return True
    try:
        data = json.loads(_marker().read_text(encoding="utf-8"))
        return not (data.get("done") and int(data.get("version", 0)) >= SETUP_VERSION)
    except (OSError, ValueError):
        return True


def mark_done(model: str) -> None:
    try:
        _marker().parent.mkdir(parents=True, exist_ok=True)
        _marker().write_text(json.dumps({"done": True, "version": SETUP_VERSION, "model": model,
                                         "at": int(time.time())}), encoding="utf-8")
    except OSError as e:
        log.warning("could not write setup marker: %s", e)


def reset_marker() -> None:
    _marker().unlink(missing_ok=True)


def write_env(updates: dict) -> None:
    """Set KEY=value lines in the per-user .env, keeping everything else (comments, other keys)."""
    path = _env_file()
    lines = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    pending = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


# ======================= Ollama helpers =======================
def _is_local_host() -> bool:
    return any(h in config.OLLAMA_HOST for h in ("127.0.0.1", "localhost", "[::1]"))


def ollama_up(timeout: float = 2) -> bool:
    try:
        with urllib.request.urlopen(config.OLLAMA_HOST + "/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


def installed_models() -> set[str]:
    try:
        with urllib.request.urlopen(config.OLLAMA_HOST + "/api/tags", timeout=3) as r:
            return {m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])}
    except Exception:
        return set()


def model_installed(model: str) -> bool:
    names = installed_models()
    return model in names or (model if ":" in model else model + ":latest") in names


def find_ollama_app() -> Path | None:
    for p in (Path("/Applications/Ollama.app"), Path.home() / "Applications" / "Ollama.app"):
        if p.is_dir():
            return p
    return None


def find_ollama_cli() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"):
        if os.access(p, os.X_OK):
            return p
    app = find_ollama_app()
    bundled = app / "Contents" / "Resources" / "ollama" if app else None
    return str(bundled) if bundled and bundled.exists() else None


# ======================= permissions =======================
def mic_status() -> str:
    """authorized | denied | restricted | undetermined | unknown (AVFoundation missing)."""
    try:
        import AVFoundation as AV
        code = int(AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeAudio))
        return {0: "undetermined", 1: "restricted", 2: "denied", 3: "authorized"}.get(code, "unknown")
    except Exception:
        return "unknown"


def request_mic() -> None:
    """Make macOS show its microphone prompt (no-op if already decided)."""
    try:
        import AVFoundation as AV
        AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeAudio, lambda ok: None)
        return
    except Exception:
        pass
    mic_probe()   # opening an input stream triggers the same prompt


def mic_probe() -> bool:
    """Record a moment of audio; a denied app gets pure digital silence."""
    try:
        import sounddevice as sd
        audio = sd.rec(int(0.5 * 16000), samplerate=16000, channels=1, dtype="float32",
                       device=config.MIC_DEVICE)
        sd.wait()
        return bool(abs(audio).max() > 0)
    except Exception:
        return False


def mic_ok() -> bool:
    status = mic_status()
    return status == "authorized" or (status == "unknown" and mic_probe())


def accessibility_trusted() -> bool:
    try:
        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:
        return False


# ======================= the runner =======================
def _fmt_bytes(n: float) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"


class _Rate:
    """Download speed over the last few seconds."""

    def __init__(self, window: float = 4.0):
        self.window = window
        self.samples: deque = deque()

    def update(self, total_done: float) -> float:
        now = time.time()
        self.samples.append((now, total_done))
        while len(self.samples) > 2 and now - self.samples[0][0] > self.window:
            self.samples.popleft()
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0


def _progress_text(done: float, total: float, rate: float) -> str:
    text = f"{_fmt_bytes(done)} of {_fmt_bytes(total)}"
    if rate > 1024:
        text += f" · {_fmt_bytes(rate)}/s"
        eta = int((total - done) / rate)
        if eta > 5:
            text += f" · {eta // 60}m {eta % 60:02d}s left" if eta >= 60 else f" · {eta}s left"
    return text


class Setup:
    def __init__(self, push=None):
        self.push = push                       # push(snapshot_dict) -> None, called from worker threads
        self.hw = hardware()
        self.model = os.getenv("JARVIS_LOCAL_MODEL") or recommend_model(self.hw["ram_gb"])
        self.whisper = config.WHISPER_MODEL
        self.steps = {sid: {"id": sid, "title": t, "title_hi": hi, "optional": opt, "status": "pending",
                            "pct": None, "detail": "", "hint": "", "actions": []}
                      for sid, t, hi, opt in STEPS}
        self.phase = "welcome"                 # welcome | running | error | done
        self.finished = False
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._skips: set[str] = set()
        self._last_push = 0.0

    # ---------- state exposed to the UI ----------
    def snapshot(self) -> dict:
        with self._lock:
            models = [dict(m, recommended=m["id"] == recommend_model(self.hw["ram_gb"])) for m in MODELS]
            if self.model not in {m["id"] for m in MODELS}:
                models.append({"id": self.model, "label": "Custom", "size_gb": model_size_gb(self.model),
                               "note": "Set in your .env file.", "recommended": False})
            return {"phase": self.phase, "hardware": dict(self.hw), "model": self.model,
                    "models": models, "whisper": self.whisper, "version": SETUP_VERSION,
                    "steps": [dict(self.steps[s]) for s in _ORDER]}

    def _emit(self, force: bool = True) -> None:
        now = time.time()
        if not force and now - self._last_push < 0.12:
            return
        self._last_push = now
        if self.push:
            try:
                self.push(self.snapshot())
            except Exception as e:
                log.debug("setup push failed: %s", e)

    def _set(self, sid: str, force: bool = True, **fields) -> None:
        with self._lock:
            self.steps[sid].update(fields)
        self._emit(force)

    def _done(self, sid: str, detail: str = "") -> None:
        self._set(sid, status="done", pct=1.0, detail=detail, hint="", actions=[])

    # ---------- controls (called from the UI thread) ----------
    def choose_model(self, model: str) -> None:
        with self._lock:
            if self.phase in ("welcome", "error") and model:
                self.model = model
        self._emit()

    def start(self, model: str | None = None) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if model:
                self.model = model
            self._cancel.clear()
            self.phase = "running"
            for st in self.steps.values():
                if st["status"] == "error":
                    st.update(status="pending", detail="", hint="", actions=[])
            self._thread = threading.Thread(target=self._run, name="friday-setup", daemon=True)
            self._thread.start()
        self._emit()

    def retry(self) -> None:
        self.start()

    def skip(self, sid: str) -> None:
        """Skip an optional step (while it is waiting, failed, or even about to run)."""
        if sid not in self.steps or not self.steps[sid]["optional"]:
            return
        self._skips.add(sid)
        with self._lock:
            if self.steps[sid]["status"] == "error":
                self.steps[sid].update(status="skipped", detail="Skipped", hint="", actions=[])
        self._emit()
        if self.phase == "error":
            self.start()

    def cancel(self) -> None:
        self._cancel.set()

    def finish(self) -> bool:
        """The user pressed "Start Friday"."""
        with self._lock:
            if self.phase != "done":
                return False
            self.finished = True
            return True

    # ---------- the sequence ----------
    def _run(self) -> None:
        try:
            self._persist_choices()
            self._check_disk()
        except SetupError as e:
            self._fail(None, e)
            return
        for sid in _ORDER:
            if self.steps[sid]["status"] in ("done", "skipped"):
                continue
            if sid in self._skips:
                self._set(sid, status="skipped", detail="Skipped", pct=None)
                continue
            self._set(sid, status="running", pct=None, detail="Checking…", hint="", actions=[])
            try:
                getattr(self, "_step_" + sid)()
            except _Cancelled:
                return
            except _Skipped:
                self._set(sid, status="skipped", detail="Skipped", pct=None, actions=[])
            except SetupError as e:
                self._fail(sid, e)
                return
            except Exception as e:
                log.exception("setup step %s crashed", sid)
                self._fail(sid, SetupError(f"Unexpected problem: {e}"))
                return
        with self._lock:
            self.phase = "done"
        mark_done(self.model)
        self._emit()

    def _fail(self, sid: str | None, err: SetupError) -> None:
        log.warning("setup step %s failed: %s", sid, err)
        with self._lock:
            self.phase = "error"
            if sid:
                self.steps[sid].update(status="error", detail=str(err), hint=err.hint,
                                       actions=err.actions, pct=None)
            else:   # a problem before any step started: show it on the first unfinished step
                first = next(s for s in _ORDER if self.steps[s]["status"] not in ("done", "skipped"))
                self.steps[first].update(status="error", detail=str(err), hint=err.hint, actions=err.actions)
        self._emit()

    def _persist_choices(self) -> None:
        write_env({"JARVIS_LOCAL_MODEL": self.model, "JARVIS_NUM_CTX": num_ctx_for(self.hw["ram_gb"])})

    def _check_disk(self) -> None:
        todo = 0.0
        if not (ollama_up() or find_ollama_app() or find_ollama_cli()):
            todo += _OLLAMA_APP_GB
        if self.steps["brain"]["status"] != "done" and not model_installed(self.model):
            todo += model_size_gb(self.model)
        if self.steps["ears"]["status"] != "done" and not self._whisper_ready():
            todo += (whisper_mb(self.whisper) or 500) / 1024
        free = free_gb()
        if todo and free < todo + 1.0:
            raise SetupError(f"Not enough free disk space: {free:.1f} GB free, about {todo + 1:.1f} GB needed.",
                             hint="Free some space (or pick the Light model), then press Retry.")

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise _Cancelled()

    def _wait_for(self, sid: str, predicate, timeout: float = 600, interval: float = 0.6) -> bool:
        """Poll until predicate() is true. False if the user skipped the step."""
        end = time.time() + timeout
        while time.time() < end:
            self._check_cancel()
            if sid in self._skips:
                return False
            if predicate():
                return True
            time.sleep(interval)
        return False

    # ---------- step: engine ----------
    def _step_engine(self) -> None:
        if ollama_up():
            return self._done("engine", "Ollama is running")
        if not _is_local_host():
            raise SetupError(f"Can't reach Ollama at {config.OLLAMA_HOST}.",
                             hint="Check OLLAMA_HOST in your .env, or remove it to use this Mac.")
        if not (find_ollama_app() or find_ollama_cli()):
            self._install_ollama()
        self._set("engine", detail="Starting Ollama…", pct=None)
        self._start_ollama()
        self._done("engine", "Ollama is running")

    def _install_ollama(self) -> None:
        manual = [{"id": "open_url", "label": "Open download page", "arg": OLLAMA_PAGE}]
        self._set("engine", detail="Downloading Ollama…", pct=0.0)
        work = Path(tempfile.mkdtemp(prefix="ollama-", dir=_ensure(config.SUPPORT_DIR)))
        try:
            zip_path = work / "Ollama.zip"
            try:
                with urllib.request.urlopen(OLLAMA_ZIP_URL, timeout=30) as r, open(zip_path, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    done, rate = 0, _Rate()
                    while True:
                        self._check_cancel()
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        self._set("engine", force=False, pct=(done / total) if total else None,
                                  detail="Downloading Ollama · " + (_progress_text(done, total, rate.update(done))
                                                                     if total else _fmt_bytes(done)))
            except (urllib.error.URLError, OSError) as e:
                raise SetupError(f"Couldn't download Ollama ({e}).",
                                 hint="Check your internet connection and retry, or install Ollama by hand.",
                                 actions=manual) from e
            self._set("engine", detail="Installing Ollama…", pct=None)
            out = work / "x"
            out.mkdir()
            if subprocess.run(["ditto", "-xk", str(zip_path), str(out)]).returncode != 0:
                raise SetupError("The Ollama download was damaged.", hint="Retry the download.", actions=manual)
            apps = list(out.glob("*.app"))
            if not apps:
                raise SetupError("The Ollama download didn't contain an app.", actions=manual)
            dest_dir = Path("/Applications")
            if not os.access(dest_dir, os.W_OK):
                dest_dir = _ensure(Path.home() / "Applications")
            dest = dest_dir / "Ollama.app"
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            if subprocess.run(["ditto", str(apps[0]), str(dest)]).returncode != 0:
                raise SetupError(f"Couldn't copy Ollama into {dest_dir}.", actions=manual)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _start_ollama(self) -> None:
        app, cli = find_ollama_app(), find_ollama_cli()
        attempts = []
        if app:
            attempts.append(lambda: subprocess.run(["open", "-g", "-a", str(app)], timeout=20))
        if cli:
            attempts.append(lambda: subprocess.Popen([cli, "serve"], stdin=subprocess.DEVNULL,
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                     start_new_session=True))
        for launch in attempts:
            try:
                launch()
            except (OSError, subprocess.SubprocessError) as e:
                log.info("ollama launch attempt failed: %s", e)
                continue
            if self._wait_for("engine", ollama_up, timeout=25, interval=0.5):
                return
        raise SetupError("Ollama is installed but isn't answering.",
                         hint="Open the Ollama app once from Applications, then press Retry.",
                         actions=[{"id": "open_url", "label": "Open download page", "arg": OLLAMA_PAGE}])

    # ---------- step: brain ----------
    def _step_brain(self) -> None:
        if not ollama_up():
            raise SetupError("The AI engine isn't running.", hint="Press Retry to start it again.")
        if model_installed(self.model):
            return self._done("brain", f"{self.model} is ready")
        last = None
        for attempt in range(4):                       # pulls resume where they stopped
            try:
                return self._pull(self.model)
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = e
                log.info("pull attempt %d failed: %s", attempt + 1, e)
                self._set("brain", detail="Connection dropped — retrying…")
                for _ in range(5 * (attempt + 1)):
                    self._check_cancel()
                    time.sleep(1)
        raise SetupError(f"Couldn't finish downloading {self.model} ({last}).",
                         hint="Check your internet connection and press Retry — it continues where it stopped.")

    def _pull(self, model: str) -> None:
        req = urllib.request.Request(config.OLLAMA_HOST + "/api/pull",
                                     data=json.dumps({"model": model, "stream": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        layers: dict[str, tuple[float, float]] = {}
        rate, ok = _Rate(), False
        self._set("brain", detail=f"Downloading {model}…", pct=0.0)
        with urllib.request.urlopen(req, timeout=60) as r:
            for raw in r:
                self._check_cancel()
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                if msg.get("error"):
                    raise SetupError(f"Ollama couldn't download {model}: {msg['error']}",
                                     hint="Check the model name in your .env, then press Retry.")
                status = msg.get("status", "")
                if msg.get("digest") and msg.get("total"):
                    layers[msg["digest"]] = (msg.get("completed", 0), msg["total"])
                if status == "success":
                    ok = True
                total = sum(t for _, t in layers.values())
                if total:
                    done = sum(c for c, _ in layers.values())
                    self._set("brain", force=False, pct=min(done / total, 0.99),
                              detail=f"Downloading {model} · " + _progress_text(done, total, rate.update(done)))
                else:
                    self._set("brain", force=False, pct=None, detail=status.capitalize() or "Working…")
        if not ok:
            raise ValueError("download ended early")
        self._done("brain", f"{model} is ready")

    # ---------- step: ears ----------
    def _whisper_dir(self) -> Path:
        try:
            from faster_whisper.utils import _MODELS
            repo = _MODELS.get(self.whisper) or f"Systran/faster-whisper-{self.whisper}"
        except Exception:
            repo = f"Systran/faster-whisper-{self.whisper}"
        try:
            from huggingface_hub.constants import HF_HUB_CACHE
            root = Path(HF_HUB_CACHE)
        except Exception:
            root = Path.home() / ".cache" / "huggingface" / "hub"
        return root / ("models--" + repo.replace("/", "--"))

    def _whisper_ready(self) -> bool:
        if os.path.isdir(self.whisper):
            return True
        try:
            from faster_whisper.utils import download_model
            download_model(self.whisper, local_files_only=True)
            return True
        except Exception:
            return False

    def _step_ears(self) -> None:
        if self._whisper_ready():
            return self._done("ears", f"Whisper “{self.whisper}” is ready")
        expected = (whisper_mb(self.whisper) or 0) * 2**20
        result: dict = {}

        def download():
            try:
                from faster_whisper.utils import download_model
                download_model(self.whisper)
            except BaseException as e:   # surfaced on the polling thread below
                result["error"] = e

        t = threading.Thread(target=download, name="whisper-download", daemon=True)
        t.start()
        rate, folder = _Rate(), self._whisper_dir()
        self._set("ears", detail=f"Downloading Whisper “{self.whisper}”…", pct=0.0 if expected else None)
        while t.is_alive():
            self._check_cancel()
            got = _dir_size(folder)
            if expected:
                self._set("ears", force=False, pct=min(got / expected, 0.99),
                          detail=f"Downloading Whisper “{self.whisper}” · "
                                 + _progress_text(min(got, expected), expected, rate.update(got)))
            else:
                self._set("ears", force=False, detail=f"Downloading Whisper “{self.whisper}” · {_fmt_bytes(got)}")
            t.join(0.5)
        if "error" in result:
            raise SetupError(f"Couldn't download the speech model ({result['error']}).",
                             hint="Check your internet connection and press Retry.")
        self._done("ears", f"Whisper “{self.whisper}” is ready")

    # ---------- step: voice ----------
    def _step_voice(self) -> None:
        from . import phrases, speak
        sp = speak._speaker
        if config.TTS_ENGINE != "neural" or not sp._edge_ok:
            return self._done("voice", "Using the built-in Mac voices")
        items = list(phrases.all_static_lines())
        self._set("voice", detail="Recording Friday's voice lines…", pct=0.0)

        def progress(i: int, n: int) -> None:
            self._check_cancel()
            self._set("voice", force=False, pct=i / n, detail=f"Recording Friday's voice lines · {i} of {n}")

        if sp.precache(items, progress=progress):
            self._done("voice", "Neural voices ready (English + हिंदी)")
        else:   # offline: not an error — Friday falls back to the Mac's own voices
            self._done("voice", "Offline for now — Friday will use the built-in Mac voices")

    # ---------- step: mic ----------
    def _step_mic(self) -> None:
        if platform.system() != "Darwin":
            return self._done("mic", "Not needed on this system")
        if mic_ok():
            return self._done("mic", "Microphone allowed")
        settings = [{"id": "open_settings", "label": "Open Microphone settings", "arg": "Microphone"}]
        status = mic_status()
        if status == "restricted":
            raise SetupError("This Mac's profile blocks microphone access.", hint="Ask your administrator.")
        if status in ("undetermined", "unknown"):
            self._set("mic", status="waiting", detail="Click “Allow” in the macOS prompt…", actions=settings)
            request_mic()
        else:
            self._set("mic", status="waiting", detail="Microphone is off for Friday. Turn it on in System Settings.",
                      actions=settings)
        if self._wait_for("mic", mic_ok, timeout=900):
            self._done("mic", "Microphone allowed")
        else:
            raise _Skipped()

    # ---------- step: accessibility ----------
    def _step_access(self) -> None:
        if platform.system() != "Darwin":
            return self._done("access", "Not needed on this system")
        if accessibility_trusted():
            return self._done("access", "Accessibility allowed")
        self._set("access", status="waiting",
                  detail="Needed to type text and press keys for you. Add Friday and switch it on.",
                  actions=[{"id": "open_settings", "label": "Open Accessibility settings", "arg": "Accessibility"}])
        if self._wait_for("access", accessibility_trusted, timeout=900):
            self._done("access", "Accessibility allowed")
        else:
            raise _Skipped()


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


# ======================= safe "open" helpers for the UI =======================
def open_settings(pane: str) -> bool:
    """Open a Privacy & Security pane (Microphone / Accessibility only)."""
    if pane not in ("Microphone", "Accessibility"):
        return False
    subprocess.Popen(["open", _SETTINGS_PREFIX + pane])
    return True


def open_url(url: str) -> bool:
    if url not in _ALLOWED_URLS:
        return False
    subprocess.Popen(["open", url])
    return True
