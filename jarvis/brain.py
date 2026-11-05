"""Brain — a local LLM served by Ollama (http://127.0.0.1:11434), fully offline.

Recommended models (must support tool calling):
  qwen2.5:7b   default — good Hindi + reliable tools, ~5 GB, runs on 16 GB Macs
  qwen2.5:14b  better Hindi and reasoning, needs ~24 GB+ RAM
  qwen2.5:3b   fastest, weaker Hindi (8 GB Macs)
  qwen3:8b     also good; thinking is disabled automatically
"""
import json
import logging
import re
import urllib.error
import urllib.request

from . import config, toolbox
from .prompts import system_prompt

log = logging.getLogger("jarvis.brain")

MAX_TOOL_ROUNDS = 6
MAX_TOOL_RESULT_CHARS = 1500   # a long shell/clipboard result must not crowd the context window


class BrainUnavailable(RuntimeError):
    pass


def _post(path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(config.OLLAMA_HOST + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        raise BrainUnavailable(f"Ollama error {e.code}: {body[:300]}") from e
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise BrainUnavailable(f"Ollama is not reachable at {config.OLLAMA_HOST} ({e})") from e


def _get(path: str, timeout: float = 3) -> dict:
    try:
        with urllib.request.urlopen(config.OLLAMA_HOST + path, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        raise BrainUnavailable(f"Ollama is not reachable at {config.OLLAMA_HOST} ({e})") from e


_TOOL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S)


def _text_tool_calls(content: str):
    """Some small models write the call as text instead of using tool_calls."""
    calls = []
    for blob in _TOOL_TAG.findall(content or ""):
        try:
            obj = json.loads(blob)
            calls.append({"function": {"name": obj["name"], "arguments": obj.get("arguments", {})}})
        except (json.JSONDecodeError, KeyError):
            pass
    if not calls:
        s = (content or "").strip().strip("`").removeprefix("json").strip()
        if s.startswith("{") and '"name"' in s:
            try:
                obj = json.loads(s)
                if obj.get("name") in toolbox._FUNCS:
                    calls.append({"function": {"name": obj["name"],
                                               "arguments": obj.get("arguments") or obj.get("parameters") or {}}})
            except json.JSONDecodeError:
                pass
    return calls


class LocalBrain:
    def __init__(self, confirm=None, on_tool=None):
        self.model = config.LOCAL_MODEL
        self.confirm = confirm          # confirm(description) -> bool
        self.on_tool = on_tool          # on_tool(name, args) for the UI timeline
        self.history: list[dict] = []

    @property
    def name(self) -> str:
        return f"{self.model} (local, Ollama)"

    # ---------- health ----------
    def check(self) -> str:
        """Raise BrainUnavailable with a helpful message, or return 'ok'."""
        tags = _get("/api/tags")
        names = {m.get("name", "") for m in tags.get("models", [])}
        base = self.model if ":" in self.model else self.model + ":latest"
        if self.model not in names and base not in names:
            raise BrainUnavailable(f"Model {self.model} isn't downloaded. Run: ollama pull {self.model}")
        return "ok"

    def warm_up(self):
        """Load the model into memory so the first real reply is fast."""
        try:
            _post("/api/chat", {"model": self.model, "messages": [{"role": "user", "content": "hi"}],
                                "stream": False, "keep_alive": "30m",
                                "options": {"num_predict": 1}}, timeout=config.LLM_TIMEOUT)
        except BrainUnavailable as e:
            log.info("warm-up skipped: %s", e)

    def reset(self):
        self.history.clear()

    # ---------- main ----------
    def handle(self, text: str, lang: str = "en") -> str:
        """Run one user turn. If anything fails half-way the history is restored,
        so a timeout never leaves an unanswered user turn or a tool call with no result."""
        checkpoint = list(self.history)
        try:
            return self._run_turn(text, lang)
        except BaseException:
            self.history = checkpoint
            raise

    def _run_turn(self, text: str, lang: str) -> str:
        self.history.append({"role": "user", "content": f"[lang={lang}] {text}"})
        self._trim()
        for _ in range(MAX_TOOL_ROUNDS):
            msg = self._chat()
            content = _THINK.sub("", msg.get("content") or "").strip()
            text_calls = [] if msg.get("tool_calls") else _text_tool_calls(content)
            calls = msg.get("tool_calls") or text_calls
            if not calls:
                self.history.append({"role": "assistant", "content": content})
                return content
            self.history.append({"role": "assistant", "content": "" if text_calls else content,
                                 "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments", {})
                if self.on_tool:
                    try:
                        self.on_tool(name, args)
                    except Exception:
                        pass
                result = toolbox.execute(name, args, confirm=self.confirm)
                log.info("tool %s -> %s", name, result[:60].replace("\n", " "))
                if len(result) > MAX_TOOL_RESULT_CHARS:
                    result = result[:MAX_TOOL_RESULT_CHARS] + " …[truncated]"
                self.history.append({"role": "tool", "content": result, "tool_name": name})
        reply = "That's taking more steps than I'd like. Let's try it a different way." if lang == "en" \
            else "इसमें बहुत सारे स्टेप लग रहे हैं, कृपया थोड़ा अलग तरीक़े से बताइए।"
        self.history.append({"role": "assistant", "content": reply})  # keep the history well-formed
        return reply

    def _chat(self) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt()}] + self.history,
            "tools": toolbox.TOOLS,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": config.TEMPERATURE, "num_ctx": config.NUM_CTX},
        }
        if re.match(r"(qwen3|deepseek-r1|gpt-oss)", self.model):
            payload["think"] = False
        data = _post("/api/chat", payload, timeout=config.LLM_TIMEOUT)
        return data.get("message", {})

    def _trim(self):
        """Keep the last MAX_HISTORY_TURNS user turns (with their tool calls)."""
        user_idx = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if len(user_idx) > config.MAX_HISTORY_TURNS:
            self.history = self.history[user_idx[-config.MAX_HISTORY_TURNS]:]
