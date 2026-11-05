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
    assert contains_wake_word("फ्राइडे। क्रोम खोलो।")          # Whisper puts a danda after the name
    assert strip_wake_word("फ्राइडे। क्रोम खोलो।") == "क्रोम खोलो"
    assert not contains_wake_word("फ्राइडेवाला क्रोम")          # still a whole-word match
    assert contains_wake_word("Frida, open Chrome")                 # common English-gate mishearing
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
    # volume shapes that used to miss the fast path
    ("volume 50", "set_volume", {"level": 50}),
    ("volume 50 percent", "set_volume", {"level": 50}),
    ("आवाज़ 30 कर दो", "set_volume", {"level": 30}),
    ("volume up 20", "change_volume", {"delta": 20}),
    ("make it louder", "change_volume", {"delta": 10}),
    ("a bit quieter", "change_volume", {"delta": -10}),
    ("turn it down", "change_volume", {"delta": -10}),
    ("mute the music", "mute", {"on": True}),
    ("unmute the sound", "mute", {"on": False}),
    # bare media words
    ("pause", "media_control", {"command": "pause"}),
    ("resume", "media_control", {"command": "play"}),
    ("previous song", "media_control", {"command": "previous"}),
    # command-shaped keyword intents still work
    ("turn on dark mode", "toggle_dark_mode", {}),
    ("lock the screen", "lock_screen", {}),
    ("what is my battery level", "get_battery", {}),
    ("goodbye", "_goodbye", {}),
    ("shut down", "_goodbye", {}),
    ("close the browser", "quit_app", {"name": "browser"}),
]

# Sentences that merely CONTAIN a keyword must not fire a command (they go to the LLM).
NOT_COMMANDS = [
    "how do I shut down a docker container", "shut down my mac", "what is dark mode",
    "how do I take a screenshot on windows", "my phone battery is dying", "what's the cpu of an m3",
    "close the door", "run the tests", "kill the lights", "explain how to lock screen on windows",
    "why is the battery draining so fast", "what does mute mean",
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


def test_keyword_sentences_are_not_commands():
    fired = [(t, commands.parse(t)) for t in NOT_COMMANDS if commands.parse(t) is not None]
    assert not fired, fired


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


# ---------------- hallucination filters & clean listening ----------------
def test_whisper_hallucinations_are_dropped():
    from jarvis.listen import PROMPTS, _is_hallucination as bad
    for junk in ["Thank you.", "Thanks for watching!", "Please subscribe to my channel", "Subtitles by the Amara.org community",
                 "धन्यवाद", "you", "...", "♪♪", "[Music]", "(music)", "한국어 자막", "Спасибо",
                 "the the the the the the", "ok ok ok ok ok ok ok",
                 "Chrome, Safari, Spotify, YouTube, WhatsApp", "फ्राइडे। क्रोम, सफारी, स्पॉटिफाई, यूट्यूब"]:
        assert bad(junk), junk
    # real commands, including the words approval relies on, must survive
    for ok in ["Friday", "open chrome", "okay", "yes", "haan kar do", "नहीं", "क्रोम खोलो", "stop", "volume 50",
               "Friday, open Chrome", "what's the time", "goodbye", "close Safari", "play something on Spotify"]:
        assert not bad(ok), ok
    # the vocabulary prompts must not be valid commands any more
    for prompt in PROMPTS.values():
        assert commands.parse(prompt) is None


def test_low_confidence_segments_are_filtered():
    from types import SimpleNamespace as NS
    from jarvis.listen import segment_ok
    assert segment_ok(NS(no_speech_prob=0.05, avg_logprob=-0.3, compression_ratio=1.4))
    assert not segment_ok(NS(no_speech_prob=0.9, avg_logprob=-1.4, compression_ratio=1.2))   # silence
    assert not segment_ok(NS(no_speech_prob=0.1, avg_logprob=-2.0, compression_ratio=1.2))   # mumble
    assert not segment_ok(NS(no_speech_prob=0.1, avg_logprob=-0.4, compression_ratio=3.5))   # loop
    assert segment_ok(NS(no_speech_prob=0.7, avg_logprob=-0.3, compression_ratio=1.2))       # confident text wins


def test_decode_retries_without_prompt_when_whisper_loops():
    from types import SimpleNamespace as NS
    from jarvis.listen import Ears
    calls = []

    class Model:
        def transcribe(self, audio, **kw):
            calls.append(kw["initial_prompt"])
            if kw["initial_prompt"]:   # loops on its own vocabulary prompt
                return iter([NS(text="Spotify, Spotify, Spotify", no_speech_prob=0.2, avg_logprob=-0.2, compression_ratio=5.5)]), None
            return iter([NS(text="open chrome", no_speech_prob=0.1, avg_logprob=-0.4, compression_ratio=1.1)]), None

    assert Ears._decode(Model(), None, "en", 1) == "open chrome"
    assert calls[0] and calls[1] is None

    calls.clear()

    class Silent:                      # nothing detected at all: no retry, no cost
        def transcribe(self, audio, **kw):
            calls.append(1)
            return iter([]), None

    assert Ears._decode(Silent(), None, "en", 1) == "" and len(calls) == 1


def test_adaptive_threshold_follows_the_room():
    from jarvis.listen import AdaptiveThreshold
    t = AdaptiveThreshold(base=0.015)
    assert t.value == 0.015
    for _ in range(100):
        t.update(0.002)                       # quiet room: never drops below the configured base
    assert t.value == 0.015
    for _ in range(2000):
        t.update(0.02)                        # fan / traffic noise
    assert 0.05 < t.value <= 0.08, t.value
    for _ in range(50):
        t.update(0.002)                       # quiet again: recovers quickly
    assert t.value < 0.03
    for _ in range(30):
        t.update(0.5)                         # a few loud blocks (speech) barely move the floor
    assert t.value <= 0.08


def test_clean_audio_removes_rumble_and_lifts_quiet_speech():
    import numpy as np
    from jarvis.listen import clean_audio
    sr = 16000
    t = np.arange(sr) / sr
    rumble = 0.2 * np.sin(2 * np.pi * 30 * t)               # 30 Hz fan thump
    speech = 0.04 * np.sin(2 * np.pi * 300 * t)
    out = clean_audio((rumble + speech).astype(np.float32), sr)
    spec = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(out.size, 1 / sr)
    assert spec[(freqs > 20) & (freqs < 40)].max() < 0.02 * spec[(freqs > 290) & (freqs < 310)].max()
    assert 0.3 < np.max(np.abs(out)) <= 0.7                  # quiet speech was brought up
    loud = (0.9 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    assert abs(float(np.max(np.abs(clean_audio(loud, sr)))) - 0.9) < 0.05   # loud audio is left alone


def _fake_mic(blocks):
    """Install a fake `sounddevice` that delivers `blocks` (50 ms each) to the callback."""
    import types
    class Stream:
        def __init__(self, callback=None, **kw): self.cb = callback
        def __enter__(self):
            for b in blocks:
                self.cb(b.reshape(-1, 1), len(b), None, None)
            return self
        def __exit__(self, *a): return False
    sys.modules["sounddevice"] = types.SimpleNamespace(InputStream=Stream)


def test_recorder_ignores_clicks_but_keeps_speech():
    import numpy as np
    from jarvis.listen import Ears
    n = 800
    rng = np.random.default_rng(0)
    quiet = lambda: (rng.standard_normal(n) * 0.002).astype(np.float32)
    loud = lambda: (rng.standard_normal(n) * 0.1).astype(np.float32)
    config.SILENCE_THRESHOLD, config.SILENCE_DURATION, config.MIN_SPEECH_SECONDS = 0.015, 0.7, 0.25
    try:
        click = [quiet() for _ in range(10)] + [loud()] + [quiet() for _ in range(20)]
        _fake_mic(click)
        assert Ears().record() is None                        # one 50 ms click is not speech
        speech = [quiet() for _ in range(10)] + [loud() for _ in range(12)] + [quiet() for _ in range(20)]
        _fake_mic(speech)
        audio = Ears().record()
        assert audio is not None and len(audio) > 12 * n
        # a noisy room (fan at ~0.03 RMS) must not count as speech once the floor is learned
        ears = Ears()
        noisy = lambda: (rng.standard_normal(n) * 0.03).astype(np.float32)
        for _ in range(200):
            ears.threshold.update(0.03)
        _fake_mic([noisy() for _ in range(30)] + [quiet() for _ in range(20)])
        assert ears.record(max_wait_for_speech=0.2) is None
    finally:
        sys.modules.pop("sounddevice", None)


# ---------------- safe-mode gating ----------------
def _gate(name, args, front="Notes"):
    from jarvis import actions
    real, actions.frontmost_app = actions.frontmost_app, (lambda: front)
    try:
        return toolbox.needs_confirmation(name, toolbox._coerce(name, args))
    finally:
        actions.frontmost_app = real


def test_context_aware_confirmation():
    assert _gate("run_shell", {"command": "ls"}) and _gate("move_to_trash", {"path": "x"})
    # typing is fine in Notes, but equals run_shell in a terminal
    assert not _gate("type_text", {"text": "hello"}, "Notes")
    assert _gate("type_text", {"text": "rm -rf ~"}, "Terminal")
    assert _gate("type_text", {"text": "rm -rf ~"}, "iTerm2")
    assert _gate("type_text", {"text": "line1\nline2"}, "Notes")          # newline submits
    assert not _gate("press_keys", {"shortcut": "cmd+t"}, "Google Chrome")
    assert _gate("press_keys", {"shortcut": "return"}, "Terminal")
    assert not _gate("press_keys", {"shortcut": "return"}, "Notes")
    assert _gate("press_keys", {"shortcut": "cmd+q"}, "Notes")
    assert _gate("press_keys", {"shortcut": "cmd+delete"}, "Finder")
    assert not _gate("get_time", {})
    # opening a folder is fine, opening an app/script is not
    assert not _gate("open_path", {"path": "downloads"})
    assert _gate("open_path", {"path": "/Applications/Safari.app"})
    assert _gate("open_path", {"path": "~/evil.command"})


def test_declined_keystrokes_do_not_run():
    from jarvis import actions
    config.SAFE_MODE = True
    real_front, actions.frontmost_app = actions.frontmost_app, (lambda: "Terminal")
    ran = []
    old = toolbox._FUNCS["type_text"]
    toolbox._FUNCS["type_text"] = lambda text: ran.append(text) or "Typed it."
    try:
        out = toolbox.execute("type_text", {"text": "rm -rf ~"}, confirm=lambda d: False)
        assert "NOT performed" in out and not ran
        assert toolbox.execute("type_text", {"text": "ls"}, confirm=lambda d: True) == "Typed it." and ran == ["ls"]
    finally:
        toolbox._FUNCS["type_text"] = old
        actions.frontmost_app = real_front


def test_url_and_folder_restrictions():
    from jarvis import actions
    actions_run, actions._run = actions._run, (lambda cmd, timeout=20: (True, ""))
    try:
        _url_checks(actions)
    finally:
        actions._run = actions_run


def _url_checks(actions):
    assert "only open web links" in actions.open_url("file:///etc/passwd")
    assert "only open web links" in actions.open_url("javascript:alert(1)")
    assert "only open web links" in actions.open_url("ssh://host")
    assert actions.open_url("github.com") == "Opened https://github.com."
    assert actions.open_url("mailto:a@b.co").startswith("Opened")
    assert "home folder" in actions.create_folder("/etc/evil")
    assert "home folder" in actions.create_folder("../../../../../tmp/evil")


def test_log_redaction():
    out = toolbox.loggable("send_email", {"to": "a@b.co", "subject": "hi", "body": "secret text"})
    assert "secret" not in str(out) and out["to"] == "a@b.co"
    assert "pw" not in str(toolbox.loggable("type_text", {"text": "my pw is 1234"}))
    assert len(toolbox.loggable("run_shell", {"command": "x" * 500})["command"]) <= 61


# ---------------- hotkey ----------------
def test_hotkey_parsing():
    from jarvis.hotkey import parse_hotkey, parse_or_default, pretty
    hk = parse_hotkey("option+j")
    assert (hk.carbon_mods, hk.keycode) == (0x0800, 38) and pretty(hk) == "⌥J"
    assert parse_hotkey("Cmd+Shift+Space").carbon_mods == 0x0100 | 0x0200
    assert parse_hotkey("ctrl+alt+f5").label == "ctrl+option+f5"
    assert parse_hotkey("f5").keycode == 96
    for bad in ("j", "option", "option+j+k", "option+ü", ""):
        try:
            parse_hotkey(bad)
            assert False, bad
        except ValueError:
            pass
    assert parse_or_default("nonsense").label == "option+j"


# ---------------- voice cache ----------------
def test_cache_pruning():
    import os
    import tempfile
    from jarvis import speak
    old_dir = config.CACHE_DIR
    with tempfile.TemporaryDirectory() as d:
        config.CACHE_DIR = Path(d)
        for i in range(5):
            f = Path(d) / f"{i}.mp3"
            f.write_bytes(b"x" * 1000)
            os.utime(f, (1000 + i, 1000 + i))      # 0 is oldest
        (Path(d) / "junk.mp3.part").write_bytes(b"x")
        freed = speak.prune_cache(max_mb=2500 / 1024 / 1024)   # keep ~2.5 kB -> 2 newest files
        left = sorted(p.name for p in Path(d).iterdir())
        config.CACHE_DIR = old_dir
    assert left == ["3.mp3", "4.mp3"] and freed == 3000, (left, freed)


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


def test_brain_history_survives_failures():
    from jarvis import brain as B
    b = B.LocalBrain()
    b.history = [{"role": "user", "content": "[lang=en] earlier"}, {"role": "assistant", "content": "ok"}]
    before = list(b.history)
    real_post = B._post
    try:
        B._post = lambda *a, **k: (_ for _ in ()).throw(B.BrainUnavailable("down"))
        try:
            b.handle("hello", "en")
            assert False
        except B.BrainUnavailable:
            pass
        assert b.history == before                       # no orphaned user turn

        # a model that never stops calling tools: history must still end on an assistant reply
        B._post = lambda *a, **k: {"message": {"content": "", "tool_calls": [
            {"function": {"name": "get_time", "arguments": {}}}]}}
        reply = b.handle("loop forever", "en")
        assert b.history[-1] == {"role": "assistant", "content": reply}
    finally:
        B._post = real_post


def test_brain_truncates_big_tool_results():
    from jarvis import brain as B
    b = B.LocalBrain()
    old = toolbox._FUNCS["get_clipboard"]
    toolbox._FUNCS["get_clipboard"] = lambda: "A" * 10000
    replies = iter([{"message": {"content": "", "tool_calls": [{"function": {"name": "get_clipboard", "arguments": {}}}]}},
                    {"message": {"content": "done"}}])
    real_post = B._post
    B._post = lambda *a, **k: next(replies)
    try:
        assert b.handle("read clipboard", "en") == "done"
    finally:
        B._post = real_post
        toolbox._FUNCS["get_clipboard"] = old
    tool_msg = [m for m in b.history if m["role"] == "tool"][0]
    assert len(tool_msg["content"]) < 1600 and tool_msg["content"].endswith("[truncated]")


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
