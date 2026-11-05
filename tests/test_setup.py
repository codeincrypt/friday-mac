"""First-run setup tests (fake Ollama, temp support dir): python tests/test_setup.py"""
import contextlib
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config, onboarding as O  # noqa: E402

@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


TMP = Path(tempfile.mkdtemp(prefix="friday-setup-test-"))
config.SUPPORT_DIR = TMP


class FakeOllama:
    """Just enough of Ollama: /api/tags and a streaming /api/pull."""

    def __init__(self, models=(), fail_pull=None):
        self.models = list(models)
        self.fail_pull = fail_pull
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                body = json.dumps({"models": [{"name": m} for m in outer.models]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200); self.end_headers()
                w = lambda o: self.wfile.write((json.dumps(o) + "\n").encode())
                if outer.fail_pull:
                    return w({"error": outer.fail_pull})
                w({"status": "pulling manifest"})
                for done in (0, 500, 1000):
                    w({"status": "pulling abc", "digest": "sha256:abc", "total": 1000, "completed": done})
                    time.sleep(0.15)
                w({"status": "pulling tiny", "digest": "sha256:def", "total": 10, "completed": 10})
                outer.models.append(req["model"])
                w({"status": "success"})

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()


def make_setup(fake, model="qwen2.5:7b"):
    config.OLLAMA_HOST = fake.url
    s = O.Setup()
    s.model = model
    s.whisper = "tiny"
    s.hw = {"ram_gb": 16, "free_gb": 100.0, "arch": "arm64", "chip": "Test"}
    return s


def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def stub_rest(s, *, voice=True):
    """Replace the machine-dependent steps so only the one under test is real."""
    s._step_ears = lambda: s._done("ears", "stub")
    s._step_voice = lambda: s._done("voice", "stub")
    s._step_mic = lambda: s._done("mic", "stub")
    s._step_access = lambda: s._done("access", "stub")
    s._check_disk = lambda: None


# ---------------- choices ----------------
def test_recommend_model():
    assert O.recommend_model(8) == "qwen2.5:3b"
    assert O.recommend_model(16) == "qwen2.5:7b"
    assert O.recommend_model(24) == "qwen2.5:7b"
    assert O.recommend_model(32) == "qwen2.5:14b"
    assert O.num_ctx_for(8) == 8192 and O.num_ctx_for(16) == 16384


def test_write_env_preserves_other_lines():
    env = TMP / ".env"
    env.write_text("# my settings\nJARVIS_LOCAL_MODEL=old\nWHISPER_MODEL=small\n")
    O.write_env({"JARVIS_LOCAL_MODEL": "qwen2.5:3b", "JARVIS_NUM_CTX": 8192})
    lines = env.read_text().splitlines()
    assert lines == ["# my settings", "JARVIS_LOCAL_MODEL=qwen2.5:3b", "WHISPER_MODEL=small", "JARVIS_NUM_CTX=8192"], lines
    env.unlink()


def test_marker_and_needs_setup(monkeypatch=None):
    import os
    for k in ("FRIDAY_SKIP_SETUP", "FRIDAY_FORCE_SETUP"):
        os.environ.pop(k, None)
    O.reset_marker()
    assert O.needs_setup()
    O.mark_done("qwen2.5:7b")
    assert not O.needs_setup()
    os.environ["FRIDAY_FORCE_SETUP"] = "1"
    assert O.needs_setup()
    os.environ["FRIDAY_SKIP_SETUP"] = "1"          # skip wins (set after the wizard finishes)
    assert not O.needs_setup()
    del os.environ["FRIDAY_FORCE_SETUP"], os.environ["FRIDAY_SKIP_SETUP"]
    O.reset_marker()
    assert O.needs_setup()


def test_open_helpers_are_whitelisted():
    assert not O.open_settings("../../etc")
    assert not O.open_url("file:///etc/passwd")
    assert not O.open_url("https://evil.example")


# ---------------- brain pull ----------------
def test_pull_reports_progress_and_installs():
    fake = FakeOllama()
    try:
        s = make_setup(fake)
        stub_rest(s)
        s._step_engine = lambda: s._done("engine", "stub")
        seen = []
        s.push = lambda snap: seen.append(next(x for x in snap["steps"] if x["id"] == "brain")["pct"])
        s.start()
        assert wait_for(lambda: s.phase == "done"), s.snapshot()
        assert "qwen2.5:7b" in fake.models
        pcts = [p for p in seen if p is not None]
        assert pcts and max(pcts) == 1.0 and any(0 < p < 1 for p in pcts), pcts
        assert "JARVIS_LOCAL_MODEL=qwen2.5:7b" in (TMP / ".env").read_text()
        assert json.loads((TMP / "setup.json").read_text())["done"]
    finally:
        fake.close(); (TMP / ".env").unlink(missing_ok=True); O.reset_marker()


def test_pull_skipped_when_model_present():
    fake = FakeOllama(models=["qwen2.5:7b"])
    try:
        s = make_setup(fake)
        stub_rest(s)
        s._step_engine = lambda: s._done("engine", "stub")
        s.start()
        assert wait_for(lambda: s.phase == "done")
        assert s.steps["brain"]["detail"].endswith("is ready")
    finally:
        fake.close(); (TMP / ".env").unlink(missing_ok=True); O.reset_marker()


def test_pull_error_then_retry():
    fake = FakeOllama(fail_pull="pull model manifest: file does not exist")
    try:
        s = make_setup(fake)
        stub_rest(s)
        s._step_engine = lambda: s._done("engine", "stub")
        s.start()
        assert wait_for(lambda: s.phase == "error")
        brain = s.steps["brain"]
        assert brain["status"] == "error" and "does not exist" in brain["detail"]
        assert s.steps["engine"]["status"] == "done"
        fake.fail_pull = None                                  # network back
        s.retry()
        assert wait_for(lambda: s.phase == "done")
        assert s.steps["brain"]["status"] == "done"
    finally:
        fake.close(); (TMP / ".env").unlink(missing_ok=True); O.reset_marker()


# ---------------- engine ----------------
def test_engine_already_running():
    fake = FakeOllama(models=["qwen2.5:7b"])
    try:
        s = make_setup(fake)
        s._step_engine()
        assert s.steps["engine"]["status"] == "done"
    finally:
        fake.close()


def test_engine_starts_installed_ollama():
    fake = FakeOllama()
    try:
        s = make_setup(fake)
        up, launched = {"v": False}, []
        with patched(O, ollama_up=lambda timeout=2: up["v"],
                     find_ollama_app=lambda: Path("/Applications/Ollama.app"),
                     find_ollama_cli=lambda: None), \
             patched(O.subprocess, run=lambda cmd, **k: (launched.append(cmd), up.__setitem__("v", True))[0]):
            s._step_engine()
        assert launched and launched[0][:3] == ["open", "-g", "-a"], launched
        assert s.steps["engine"]["status"] == "done"
    finally:
        fake.close()


def test_engine_remote_host_unreachable_is_a_clear_error():
    config.OLLAMA_HOST = "http://10.255.255.1:11434"
    s = O.Setup()
    with patched(O, ollama_up=lambda timeout=2: False):
        try:
            s._step_engine()
            assert False, "should raise"
        except O.SetupError as e:
            assert "OLLAMA_HOST" in e.hint


# ---------------- disk / permissions / skipping ----------------
def test_not_enough_disk_stops_before_downloading():
    fake = FakeOllama()
    try:
        s = make_setup(fake)
        with patched(O, free_gb=lambda path=None: 1.0, find_ollama_app=lambda: Path("/x")):
            s.start()
            assert wait_for(lambda: s.phase == "error")
        assert "disk space" in s.steps["engine"]["detail"]
        assert "qwen2.5:7b" not in fake.models
    finally:
        fake.close(); (TMP / ".env").unlink(missing_ok=True)


def test_permission_step_waits_then_continues_and_can_be_skipped():
    fake = FakeOllama(models=["qwen2.5:7b"])
    try:
        s = make_setup(fake)
        stub_rest(s)
        s._step_engine = lambda: s._done("engine", "stub")
        granted = {"v": False}
        with patched(O, mic_ok=lambda: granted["v"], mic_status=lambda: "denied"), \
             patched(O.platform, system=lambda: "Darwin"):
            _permission_flow(fake, s, granted)
    finally:
        fake.close(); (TMP / ".env").unlink(missing_ok=True); O.reset_marker()


def _permission_flow(fake, s, granted):
    s._step_mic = O.Setup._step_mic.__get__(s)
    s.start()
    assert wait_for(lambda: s.steps["mic"]["status"] == "waiting")
    assert s.steps["mic"]["actions"][0]["arg"] == "Microphone"
    granted["v"] = True                                    # user flips the switch
    assert wait_for(lambda: s.phase == "done")
    assert s.steps["mic"]["status"] == "done"

    # again, but the user skips instead
    s2 = make_setup(fake)
    stub_rest(s2)
    s2._step_engine = lambda: s2._done("engine", "stub")
    granted["v"] = False
    s2._step_mic = O.Setup._step_mic.__get__(s2)
    s2.start()
    assert wait_for(lambda: s2.steps["mic"]["status"] == "waiting")
    s2.skip("mic")
    assert wait_for(lambda: s2.phase == "done")
    assert s2.steps["mic"]["status"] == "skipped"
    s2.skip("brain")                                       # required steps can't be skipped
    assert "brain" not in s2._skips


def test_snapshot_is_json_serialisable():
    fake = FakeOllama()
    try:
        snap = make_setup(fake).snapshot()
        json.dumps(snap, ensure_ascii=False)
        assert [s["id"] for s in snap["steps"]] == ["engine", "brain", "ears", "voice", "mic", "access"]
        assert sum(m["recommended"] for m in snap["models"]) == 1
    finally:
        fake.close()


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
        print("✓", f.__name__)
    print(f"{len(fns)} passed")
