"""Assistant state-machine test with a scripted microphone and fake speaker.
Run: python tests/test_flow.py"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import actions, assistant as A, config, toolbox  # noqa: E402
from jarvis.listen import Heard  # noqa: E402


class ScriptedEars:
    def __init__(self, lines):
        self.lines = list(lines)
        self.stop_event = threading.Event()

    def load(self):
        pass

    def listen(self, max_wait_for_speech=None, force_lang=None, wake_gate=False):
        time.sleep(0.01)
        if not self.lines:
            return None
        item = self.lines.pop(0)
        return Heard(*item) if item else None


class Recorder(A.Callbacks):
    def __init__(self):
        self.events = []

    def state(self, s, d=""): self.events.append(("state", s))
    def message(self, r, t, l="en"): self.events.append((r, t, l))
    def tool(self, n, a): self.events.append(("tool", n))
    def approval(self, d): self.events.append(("approval", d))
    def quit(self): self.events.append(("quit",))


def run(lines, typed=()):
    spoken = []
    A.speak = lambda text, lang=None: spoken.append((lang, text))
    A.precache = lambda items: None
    config.OLLAMA_HOST = "http://127.0.0.1:9"   # brain offline
    ui = Recorder()
    a = A.Assistant(ui)
    a.ears = ScriptedEars(lines)
    for t in typed:
        a.submit_text(t)
    th = threading.Thread(target=a.run, daemon=True)
    th.start()
    th.join(timeout=3)
    a.running = False
    return spoken, ui.events


def main():
    calls = []
    toolbox._FUNCS["change_volume"] = lambda delta: calls.append(("vol", delta)) or "Volume set to 40 percent."
    toolbox._FUNCS["open_app"] = lambda name: calls.append(("open", name)) or f"Opened {actions.resolve_app(name)}."
    toolbox._FUNCS["run_shell"] = lambda command: calls.append(("sh", command)) or "ran"

    # 1. wake word + command in one breath, Hinglish -> Hindi reply; then goodbye
    spoken, ev = run([("Friday volume kam karo", "en"), None, ("फ्राइडे", "hi"), ("अलविदा", "hi")])
    assert ("vol", -10) in calls, calls
    assert ("hi", "आवाज़ 40 प्रतिशत कर दी।") in spoken, spoken
    assert any(e == ("quit",) for e in ev)
    print("✓ wake word + Hinglish command + Hindi reply + goodbye")

    # 2. wake word alone -> acknowledgement -> Hindi command
    calls.clear()
    spoken, ev = run([("फ्राइडे", "hi"), ("क्रोम खोलो", "hi"), None, ("Friday goodbye", "en")])
    assert ("open", "क्रोम") in calls
    assert ("hi", "Google Chrome खोल दिया।") in spoken
    acks = [s for s in spoken if s[1] in ("जी सर?", "जी, बताइए।", "हुक्म कीजिए।", "सुन रहा हूँ सर।")]
    assert acks, spoken
    print("✓ wake ack in Hindi + Devanagari command")

    # 3. no wake word -> ignored
    calls.clear()
    spoken, ev = run([("open chrome", "en"), ("Friday goodbye", "en")])
    assert not calls
    print("✓ speech without wake word ignored")

    # 4. brain offline -> graceful bilingual message
    spoken, ev = run([("Friday tell me a joke", "en"), None, ("Friday goodbye", "en")])
    assert any("reasoning core is offline" in s[1] for s in spoken), spoken
    print("✓ LLM offline handled gracefully")

    # 5. typed command
    calls.clear()
    spoken, ev = run([("Friday goodbye", "en")], typed=["open safari"])
    assert ("open", "safari") in calls
    print("✓ typed command")

    # 6. approval by voice: "nahi" declines
    config.SAFE_MODE = True
    a = A.Assistant(Recorder())
    a.ears = ScriptedEars([("नहीं", "hi")])
    A.speak = lambda *x, **k: None
    a.last_lang = "hi"
    out = toolbox.execute("run_shell", {"command": "ls"}, confirm=a._confirm)
    assert "NOT performed" in out
    a.ears = ScriptedEars([("haan kar do", "en")])
    out = toolbox.execute("run_shell", {"command": "ls"}, confirm=a._confirm)
    assert out == "ran"
    print("✓ voice approval: नहीं declines, 'haan kar do' approves")
    print("all flow tests passed")


if __name__ == "__main__":
    main()
