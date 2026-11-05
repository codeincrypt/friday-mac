"""Assistant orchestration — the state machine that ties ears, brain, hands
and mouth together. UI-agnostic: the Mac app (app.py) and the terminal
runner (main.py) both drive this class through callbacks.

States: loading · wake (waiting for "Friday") · listening · thinking ·
        executing · speaking · approval · sleeping · error
"""
import logging
import queue
import re
import threading
import time

from . import commands, config, phrases, toolbox
from .brain import BrainUnavailable, LocalBrain
from .lang import detect_language
from .listen import Ears, contains_wake_word, strip_wake_word
from .speak import precache, speak, stop_speaking

log = logging.getLogger("jarvis.assistant")

YES = re.compile(r"\b(yes|yeah|yep|yup|sure|go ahead|do it|proceed|confirm|ok|okay|haan|haa|han|ha|ji|haan ji|"
                 r"theek hai|thik hai|kar do|bilkul)\b|हाँ|हां|जी|ठीक है|कर दो|बिल्कुल|बिलकुल|ओके", re.I)
NO = re.compile(r"\b(no|nope|cancel|stop|don't|dont|nahi|nahin|mat|ruko|rehne do)\b|नहीं|नही|मत|रुको|रहने दो|कैंसल", re.I)


class Callbacks:
    """Override any of these in the UI layer."""
    def state(self, state: str, detail: str = ""): ...
    def message(self, role: str, text: str, lang: str = "en"): ...
    def level(self, rms: float): ...
    def tool(self, name: str, args: dict): ...
    def approval(self, description: str | None): ...  # None = clear
    def quit(self): ...


class Assistant:
    def __init__(self, ui: Callbacks | None = None):
        self.ui = ui or Callbacks()
        self.ears = Ears(level_callback=lambda r: self.ui.level(r))
        self.brain = LocalBrain(confirm=self._confirm, on_tool=self._on_tool)
        self.brain_ok = False
        self.state = "loading"
        self.sleeping = not config.WAKE_WORD_ENABLED
        self.running = True
        self.last_lang = "en"
        self._typed: "queue.Queue[str]" = queue.Queue()
        self._ptt = threading.Event()        # push-to-talk requested
        self._approval_answer: bool | None = None
        self._approval_event = threading.Event()

    # ================= public controls (called from the UI thread) =========
    def push_to_talk(self):
        """Start listening for a command right now (orb click / hotkey)."""
        stop_speaking()
        self.sleeping = False
        self._ptt.set()
        self.ears.stop_event.set()  # break out of wake-word listening

    def submit_text(self, text: str):
        text = (text or "").strip()
        if text:
            stop_speaking()
            self._typed.put(text)
            self.ears.stop_event.set()

    def stop(self):
        """Stop talking / listening immediately."""
        stop_speaking()
        self.ears.stop_event.set()

    def toggle_sleep(self):
        self.sleeping = not self.sleeping
        self.ears.stop_event.set()
        self._set("sleeping" if self.sleeping else "wake")

    def answer_approval(self, approved: bool):
        self._approval_answer = approved
        self._approval_event.set()
        self.ears.stop_event.set()

    def set_language(self, mode: str):
        if mode in ("auto", "en", "hi"):
            config.LANGUAGE_MODE = mode

    def shutdown(self):
        self.running = False
        self.stop()

    # ================= main loop (runs on a worker thread) =================
    def run(self):
        self._set("loading", "Loading speech model…")
        try:
            self.ears.load()
        except Exception as e:
            log.exception("whisper load failed")
            self._set("error", f"Speech model failed to load: {e}")
            self._say(f"I couldn't load my speech model. {e}", "en")
        self._check_brain()
        precache(phrases.all_static_lines())
        lang = config.LANGUAGE_MODE if config.LANGUAGE_MODE in ("hi", "en") else "en"
        self._say(phrases.line("greeting", lang), lang)

        while self.running:
            try:
                self._tick()
            except Exception as e:  # never let the loop die
                log.exception("loop error")
                self._set("error", str(e))
                time.sleep(1)

    def _tick(self):
        # 1. typed commands take priority
        try:
            text = self._typed.get_nowait()
            self._converse(text, detect_language(text), typed=True)
            return
        except queue.Empty:
            pass

        # 2. push-to-talk
        if self._ptt.is_set():
            self._ptt.clear()
            self._listen_for_command(ack=False)
            return

        # 3. sleeping: mic off
        if self.sleeping:
            self._set("sleeping")
            time.sleep(0.2)
            return

        # 4. wait for the wake word
        self._set("wake")
        heard = self.ears.listen(wake_gate=True)
        if heard is None or self._ptt.is_set() or not self._typed.empty():
            return
        log.info("wake word heard%s", f": {heard.text}" if config.LOG_TRANSCRIPTS else "")
        if not contains_wake_word(heard.text):
            return
        rest = strip_wake_word(heard.text)
        lang = commands.reply_language(heard.text, heard.lang)
        if len(rest) > 2:              # "Friday, open Chrome" in one breath
            self._converse(rest, lang)
        else:
            self._say(phrases.line("wake_ack", lang), lang)
            self._listen_for_command(ack=False)

    def _listen_for_command(self, ack: bool):
        if ack:
            self._say(phrases.line("wake_ack", self.last_lang), self.last_lang)
        self._set("listening")
        heard = self.ears.listen(max_wait_for_speech=7)
        if heard is None:
            if not self._typed.empty() or self._ptt.is_set():
                return
            self._set("wake")
            return
        self._converse(heard.text, commands.reply_language(heard.text, heard.lang))

    def _converse(self, text: str, lang: str, typed: bool = False):
        """Handle one request, then keep the mic open for follow-ups."""
        while self.running and text:
            self.last_lang = lang
            self.ui.message("user", text, lang)
            if self._handle(text, lang) == "exit-conversation" or typed:
                return
            self._set("listening", "follow-up")
            heard = self.ears.listen(max_wait_for_speech=config.CONVERSATION_TIMEOUT)
            if heard is None:
                return
            text = strip_wake_word(heard.text) if contains_wake_word(heard.text) else heard.text
            lang = commands.reply_language(heard.text, heard.lang)

    def _handle(self, text: str, lang: str) -> str | None:
        cmd = commands.parse(text)
        if cmd and cmd.tool == "_goodbye":
            self._say(phrases.line("goodbye", lang), lang)
            self.running = False
            self.ui.quit()
            return "exit-conversation"
        if cmd and cmd.tool == "_sleep":
            self._say(phrases.line("sleep", lang), lang)
            self.sleeping = True
            return "exit-conversation"
        if cmd and cmd.tool == "_stop":
            stop_speaking()
            return "exit-conversation"

        if cmd:  # fast path: no LLM needed
            self._set("executing", cmd.tool)
            self._on_tool(cmd.tool, cmd.args)
            result = toolbox.execute(cmd.tool, cmd.args, confirm=self._confirm)
            reply = commands.respond(cmd, result, lang)
            self.brain.history += [{"role": "user", "content": f"[lang={lang}] {text}"},
                                   {"role": "assistant", "content": reply}]
            self._say(reply, lang)
            return None

        if not self.brain_ok and not self._check_brain():
            self._say(phrases.line("no_brain", lang), lang)
            return "exit-conversation"
        self._set("thinking")
        try:
            reply = self.brain.handle(text, lang)
        except BrainUnavailable as e:
            log.warning("brain unavailable: %s", e)
            self.brain_ok = False
            self._set("error", str(e))
            self._say(phrases.line("no_brain", lang), lang)
            return "exit-conversation"
        except Exception as e:
            log.exception("brain error")
            self._set("error", str(e))
            self._say(phrases.line("error", lang), lang)
            return None
        reply_lang = lang if detect_language(reply) == lang else detect_language(reply)
        self._say(reply or phrases.line("done", lang), reply_lang)
        return None

    # ================= helpers =================
    def _check_brain(self) -> bool:
        try:
            self.brain.check()
            self.brain_ok = True
            threading.Thread(target=self.brain.warm_up, daemon=True).start()
            self.ui.message("system", f"Brain online: {self.brain.name}")
        except BrainUnavailable as e:
            self.brain_ok = False
            self.ui.message("system", f"Local brain offline — {e}. Quick commands still work.")
        return self.brain_ok

    def _set(self, state: str, detail: str = ""):
        if state != self.state or detail:
            self.state = state
            self.ui.state(state, detail)

    def _say(self, text: str, lang: str):
        self._set("speaking")
        self.ui.message("jarvis", text, lang)
        speak(text, lang)

    def _on_tool(self, name, args):
        self._set("executing", name)
        self.ui.tool(name, args if isinstance(args, dict) else {})

    def _confirm(self, description: str) -> bool:
        """Ask by voice AND in the UI; whichever answers first wins."""
        lang = self.last_lang
        self._approval_answer = None
        self._approval_event.clear()
        self.ui.approval(description)
        self._say(phrases.line("confirm", lang), lang)
        self._set("approval", description)
        deadline = time.time() + 20
        while time.time() < deadline and not self._approval_event.is_set():
            heard = self.ears.listen(max_wait_for_speech=min(6, deadline - time.time()))
            if self._approval_event.is_set():
                break
            if heard:
                if NO.search(heard.text):
                    self._approval_answer = False
                    break
                if YES.search(heard.text):
                    self._approval_answer = True
                    break
        self.ui.approval(None)
        ok = bool(self._approval_answer)
        if not ok:
            self._say(phrases.line("cancelled", lang), lang)
        self._set("executing")
        return ok
