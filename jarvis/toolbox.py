"""Single source of truth for tools: schemas (Ollama / OpenAI function format),
validation, execution, and safe-mode confirmation.

To add a tool: implement it in actions.py, add a schema to TOOLS, map it in
_FUNCS. Destructive tools go in NEEDS_CONFIRMATION.
"""
import json
import logging

from . import actions, config

log = logging.getLogger("jarvis.tools")


def _tool(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []},
    }}


S = {"type": "string"}
I = {"type": "integer"}

TOOLS = [
    _tool("open_app", "Open a macOS application by name, e.g. 'Google Chrome', 'Notes'.",
          {"name": S}, ["name"]),
    _tool("quit_app", "Quit a running application.", {"name": S}, ["name"]),
    _tool("list_running_apps", "List the visible running applications."),
    _tool("open_url", "Open a website URL in the default browser.", {"url": S}, ["url"]),
    _tool("web_search", "Search Google for a query in the browser.", {"query": S}, ["query"]),
    _tool("youtube_search", "Search YouTube for videos or songs.", {"query": S}, ["query"]),
    _tool("set_volume", "Set output volume, 0-100.", {"level": I}, ["level"]),
    _tool("change_volume", "Raise or lower volume by a delta, e.g. 10 or -10.", {"delta": I}, ["delta"]),
    _tool("mute", "Mute (on=true) or unmute (on=false) the speakers.", {"on": {"type": "boolean"}}, ["on"]),
    _tool("media_control", "Control music playback in Spotify or Music.",
          {"command": {"type": "string", "enum": ["play", "pause", "playpause", "next", "previous"]},
           "app": S}, ["command"]),
    _tool("get_time", "Get the current local time."),
    _tool("get_date", "Get today's date."),
    _tool("get_battery", "Get battery level and charging state."),
    _tool("system_status", "Get CPU, memory, disk and battery status."),
    _tool("find_files", "Find files by name using Spotlight. folder may be desktop, documents, downloads, pictures or a path.",
          {"query": S, "folder": S}, ["query"]),
    _tool("open_path", "Open a file or folder (desktop, downloads, a full path...).", {"path": S}, ["path"]),
    _tool("create_folder", "Create a folder (relative paths go on the Desktop).", {"path": S}, ["path"]),
    _tool("move_to_trash", "Move a file or folder to the Trash.", {"path": S}, ["path"]),
    _tool("type_text", "Type text into the frontmost app.", {"text": S}, ["text"]),
    _tool("press_keys", "Press a keyboard shortcut like 'cmd+t' or 'return'.", {"shortcut": S}, ["shortcut"]),
    _tool("get_clipboard", "Read the clipboard text."),
    _tool("set_clipboard", "Copy text to the clipboard.", {"text": S}, ["text"]),
    _tool("take_screenshot", "Save a screenshot of the screen to the Desktop."),
    _tool("lock_screen", "Turn off the display / lock the screen."),
    _tool("toggle_dark_mode", "Switch between light and dark mode."),
    _tool("send_email", "Send an email with Apple Mail.", {"to": S, "subject": S, "body": S}, ["to", "subject", "body"]),
    _tool("run_shell", "Run a zsh shell command on the Mac and return its output.", {"command": S}, ["command"]),
]

_FUNCS = {
    "open_app": actions.open_app, "quit_app": actions.quit_app,
    "list_running_apps": actions.list_running_apps, "open_url": actions.open_url,
    "web_search": actions.web_search, "youtube_search": actions.youtube_search,
    "set_volume": actions.set_volume, "change_volume": actions.change_volume,
    "mute": actions.mute, "media_control": actions.media_control,
    "get_time": actions.get_time, "get_date": actions.get_date,
    "get_battery": actions.get_battery, "system_status": actions.system_status,
    "find_files": actions.find_files, "open_path": actions.open_path,
    "create_folder": actions.create_folder, "move_to_trash": actions.move_to_trash,
    "type_text": actions.type_text, "press_keys": actions.press_keys,
    "get_clipboard": actions.get_clipboard, "set_clipboard": actions.set_clipboard,
    "take_screenshot": actions.take_screenshot, "lock_screen": actions.lock_screen,
    "toggle_dark_mode": actions.toggle_dark_mode, "send_email": actions.send_email,
    "run_shell": actions.run_shell,
}

NEEDS_CONFIRMATION = {"send_email", "run_shell", "move_to_trash"}

assert {t["function"]["name"] for t in TOOLS} == set(_FUNCS), "TOOLS and _FUNCS out of sync"

_SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}


def describe(name: str, args: dict) -> str:
    if name == "send_email":
        return f"send an email to {args.get('to')} — subject: {args.get('subject')!r}"
    if name == "run_shell":
        return f"run the shell command: {args.get('command')}"
    if name == "move_to_trash":
        return f"move to Trash: {args.get('path')}"
    return f"{name}({json.dumps(args, ensure_ascii=False)})"


def _coerce(name: str, args) -> dict:
    """Validate and coerce model-produced arguments against the schema."""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            raise ValueError("arguments were not valid JSON")
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    schema = _SCHEMAS[name]
    props = schema["properties"]
    clean = {}
    for key, val in args.items():
        if key not in props:
            continue  # drop hallucinated params
        typ = props[key].get("type")
        if typ == "integer":
            val = int(float(val))
        elif typ == "boolean":
            val = val if isinstance(val, bool) else str(val).lower() in ("true", "1", "yes", "on")
        elif typ == "string":
            val = str(val)
            if "enum" in props[key] and val not in props[key]["enum"]:
                raise ValueError(f"{key} must be one of {props[key]['enum']}")
        clean[key] = val
    missing = [r for r in schema["required"] if r not in clean]
    if missing:
        raise ValueError(f"missing required argument(s): {', '.join(missing)}")
    return clean


def execute(name: str, args, confirm=None) -> str:
    """Run a tool. `confirm(description) -> bool` gates destructive tools."""
    if name not in _FUNCS:
        return f"Unknown tool {name}."
    try:
        args = _coerce(name, args)
    except (ValueError, TypeError) as e:
        return f"Invalid arguments for {name}: {e}"
    if config.SAFE_MODE and name in NEEDS_CONFIRMATION:
        if confirm is None or not confirm(describe(name, args)):
            return "The user declined, so this action was NOT performed."
    log.info("tool %s %s", name, args)
    try:
        return _FUNCS[name](**args)
    except Exception as e:
        log.exception("tool %s failed", name)
        return f"{name} failed: {e}"
