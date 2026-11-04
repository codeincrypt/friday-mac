"""Offline unit tests: python -m pytest tests -q   (or python tests/test_core.py)"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import commands, config, toolbox  # noqa: E402
from jarvis.lang import detect_language  # noqa: E402
from jarvis.listen import contains_wake_word, strip_wake_word  # noqa: E402


# ---------------- language ----------------
def test_language_detection():
    assert detect_language("open chrome") == "en"
    assert detect_language("what is the time") == "en"
    assert detect_language("क्रोम खोलो") == "hi"
    assert detect_language("chrome kholo") == "hi"
    assert detect_language("volume kam karo") == "hi"
    assert detect_language("mujhe batao aaj kya date hai") == "hi"
    assert detect_language("do it") == "en"
    assert detect_language("set a timer to ten") == "en"


# ---------------- wake word ----------------
def test_wake_word():
    assert contains_wake_word("Hey Friday, open Chrome")
    assert contains_wake_word("Friday")
    assert contains_wake_word("friday, what's the time?")
    assert contains_wake_word("Okay Friday volume kam karo")
    assert contains_wake_word("फ्राइडे क्रोम खोलो")
    assert contains_wake_word("Open Chrome, Friday.")
    assert not contains_wake_word("open chrome")
    assert not contains_wake_word("Jarvis, open Chrome")           # old name no longer wakes
    # "Friday" the weekday must not wake or get stripped mid-sentence
    assert not contains_wake_word("remind me on Friday")
    assert not contains_wake_word("what's the plan for Friday morning")
    assert not contains_wake_word("Fridays are great")
    assert strip_wake_word("Hey Friday, open Chrome.") == "open Chrome"
    assert strip_wake_word("फ्राइडे, क्रोम खोलो") == "क्रोम खोलो"
    assert strip_wake_word("Open Chrome, Friday.") == "Open Chrome"
    assert strip_wake_word("Friday") == ""
    assert strip_wake_word("remind me on Friday") == "remind me on Friday"


# ---------------- speech chunking ----------------
def test_split_sentences():
    from jarvis.speak import split_sentences
    assert split_sentences("Done.") == ["Done."]
    assert split_sentences("Paris, sir. Rather a lovely city, if a trifle crowded. Anything else?") == \
        ["Paris, sir. Rather a lovely city, if a trifle crowded.", "Anything else?"]
    assert split_sentences("मैं फ्राइडे हूँ। बताइए क्या करना है? मैं सुन रहा हूँ।")[0].startswith("मैं फ्राइडे हूँ।")
    long = " ".join(f"This is sentence number {i} of a long reply." for i in range(9))
    assert len(split_sentences(long)) <= 4


# ---------------- fast commands ----------------
CASES = [
    ("open chrome", "open_app", {"name": "chrome"}),
    ("Friday, open VS Code please", "open_app", {"name": "vs code"}),
    ("क्रोम खोलो", "open_app", {"name": "क्रोम"}),
    ("सफारी खोल दो", "open_app", {"name": "सफारी"}),
    ("chrome kholo", "open_app", {"name": "chrome"}),
    ("whatsapp open karo", "open_app", {"name": "whatsapp"}),
    ("open downloads", "open_path", {"path": "downloads"}),
    ("डाउनलोड्स खोलो", "open_path", {"path": "डाउनलोड्स"}),
    ("open github.com", "open_url", {"url": "github.com"}),
    ("close safari", "quit_app", {"name": "safari"}),
    ("क्रोम बंद करो", "quit_app", {"name": "क्रोम"}),
    ("spotify band karo", "quit_app", {"name": "spotify"}),
    ("what's the time", "get_time", {}),
    ("कितने बजे हैं", "get_time", {}),
    ("time kya hai", "get_time", {}),
    ("आज क्या तारीख है", "get_date", {}),
    ("battery kitni hai", "get_battery", {}),
    ("बैटरी कितनी है", "get_battery", {}),
    ("how is my mac doing", "system_status", {}),
    ("volume up", "change_volume", {"delta": 10}),
    ("आवाज़ बढ़ाओ", "change_volume", {"delta": 10}),
    ("volume kam karo", "change_volume", {"delta": -10}),
    ("set volume to 40", "set_volume", {"level": 40}),
    ("आवाज़ 30 पर कर दो", "set_volume", {"level": 30}),
    ("आवाज़ बंद करो", "mute", {"on": True}),
    ("mute", "mute", {"on": True}),
    ("गाना रोको", "media_control", {"command": "pause"}),
    ("अगला गाना", "media_control", {"command": "next"}),
    ("next song", "media_control", {"command": "next"}),
    ("play lofi beats on youtube", "youtube_search", {"query": "lofi beats"}),
    ("यूट्यूब पर अरिजीत सिंह के गाने चलाओ", "youtube_search", {"query": "अरिजीत सिंह के गाने"}),
    ("youtube pe kishore kumar songs lagao", "youtube_search", {"query": "kishore kumar songs"}),
    ("search for best mirrorless camera 2026", "web_search", {"query": "best mirrorless camera 2026"}),
    ("गूगल पर दिल्ली का मौसम सर्च करो", "web_search", {"query": "दिल्ली का मौसम"}),
    ("python tutorial search karo", "web_search", {"query": "python tutorial"}),
    ("take a screenshot", "take_screenshot", {}),
    ("स्क्रीनशॉट लो", "take_screenshot", {}),
    ("goodbye friday", "_goodbye", {}),
    ("अलविदा", "_goodbye", {}),
    ("stop listening", "_sleep", {}),
    ("सो जाओ", "_sleep", {}),
    ("stop", "_stop", {}),
    ("रुको", "_stop", {}),
]


def test_fast_commands():
    failures = []
    for text, tool, args in CASES:
        cmd = commands.parse(text)
        got = (cmd.tool, cmd.args) if cmd else None
        if got != (tool, args):
            failures.append(f"{text!r}: expected {(tool, args)}, got {got}")
    assert not failures, "\n".join(failures)


def test_llm_fallthrough():
    # multi-step or open-ended requests must go to the LLM
    for text in ["open chrome and search for cats", "क्रोम खोलो और जीमेल चेक करो",
                 "write an email to riya about the demo", "tell me a joke", "मुझे एक कहानी सुनाओ",
                 "who is the prime minister"]:
        assert commands.parse(text) is None, text


def test_hindi_replies():
    c = commands.Command("open_app", {"name": "क्रोम"})
    assert commands.respond(c, "Opened Google Chrome.", "hi") == "Google Chrome खोल दिया।"
    assert commands.respond(c, "I couldn't find an app called क्रोम.", "hi").startswith("माफ़")
    b = commands.Command("get_battery")
    assert commands.respond(b, "Battery is at 82 percent, charging.", "hi") == "बैटरी 82 प्रतिशत है, चार्ज हो रही है।"
    v = commands.Command("change_volume", {"delta": 10})
    assert commands.respond(v, "Volume set to 60 percent.", "hi") == "आवाज़ 60 प्रतिशत कर दी।"
    assert commands.respond(v, "Volume set to 60 percent.", "en") == "Volume set to 60 percent."
    assert "बजे" in commands.respond(commands.Command("get_time"), "It's 4:05 PM.", "hi") \
        or "बजकर" in commands.respond(commands.Command("get_time"), "It's 4:05 PM.", "hi")


def test_app_aliases():
    from jarvis.actions import resolve_app
    assert resolve_app("क्रोम") == "Google Chrome"
    assert resolve_app("vs code") == "Visual Studio Code"
    assert resolve_app("Some Unknown App") == "Some Unknown App"


# ---------------- toolbox validation ----------------
def test_toolbox_validation_and_confirmation():
    assert "missing required" in toolbox.execute("open_app", {})
    assert "Unknown tool" in toolbox.execute("format_disk", {})
    config.SAFE_MODE = True
    asked = []
    out = toolbox.execute("run_shell", {"command": "echo hi"}, confirm=lambda d: asked.append(d) or False)
    assert "NOT performed" in out and asked and "echo hi" in asked[0]
    # string args and coercion
    assert toolbox._coerce("set_volume", '{"level": "45"}') == {"level": 45}
    assert toolbox._coerce("mute", {"on": "true", "bogus": 1}) == {"on": True}


# ---------------- brain loop against a fake Ollama ----------------
class FakeOllama(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.calls.append(req)
        last = req["messages"][-1]
        if last["role"] == "user":
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}]}
        elif last["role"] == "tool" and last.get("tool_name") == "get_time":
            # second round: model writes a tool call as text (small-model quirk)
            msg = {"role": "assistant", "content": '<tool_call>{"name": "get_date", "arguments": {}}</tool_call>'}
        else:
            msg = {"role": "assistant", "content": "<think>x</think>जी सर, अभी समय और तारीख बता दी।"}
        body = json.dumps({"message": msg}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)


def test_brain_tool_loop():
    srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    config.OLLAMA_HOST = f"http://127.0.0.1:{srv.server_port}"
    config.LOCAL_MODEL = "qwen2.5:7b"
    from jarvis.brain import LocalBrain
    seen = []
    b = LocalBrain(on_tool=lambda n, a: seen.append(n))
    b.model = "qwen2.5:7b"
    assert b.check() == "ok"
    reply = b.handle("समय और तारीख बताओ", "hi")
    assert reply == "जी सर, अभी समय और तारीख बता दी।"
    assert seen == ["get_time", "get_date"]
    sent = FakeOllama.calls[0]
    assert sent["messages"][-1]["content"].startswith("[lang=hi]")
    assert len(sent["tools"]) == len(toolbox.TOOLS)
    srv.shutdown()


def test_brain_unavailable():
    from jarvis.brain import BrainUnavailable, LocalBrain
    config.OLLAMA_HOST = "http://127.0.0.1:9"
    b = LocalBrain()
    try:
        b.check()
        assert False, "should raise"
    except BrainUnavailable as e:
        assert "not reachable" in str(e)


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
        print("✓", f.__name__)
    print(f"{len(fns)} passed")
