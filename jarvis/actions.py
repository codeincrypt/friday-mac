"""Hands — macOS actions via AppleScript (osascript) and shell primitives.
Every action returns a short, human-readable result string; that string is
fed back to the model (or spoken directly by the fast command engine)."""
import os
import re
import shutil
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

HOME = Path.home()

# Spoken names (English, Hindi, Hinglish) -> real application names.
APP_ALIASES = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome", "क्रोम": "Google Chrome",
    "गूगल क्रोम": "Google Chrome", "browser": "Google Chrome", "ब्राउज़र": "Google Chrome",
    "ब्राउजर": "Google Chrome", "safari": "Safari", "सफारी": "Safari",
    "vs code": "Visual Studio Code", "vscode": "Visual Studio Code", "visual studio code": "Visual Studio Code",
    "code": "Visual Studio Code", "वीएस कोड": "Visual Studio Code", "वी एस कोड": "Visual Studio Code",
    "terminal": "Terminal", "टर्मिनल": "Terminal", "finder": "Finder", "फाइंडर": "Finder",
    "notes": "Notes", "नोट्स": "Notes", "music": "Music", "म्यूजिक": "Music", "म्यूज़िक": "Music",
    "spotify": "Spotify", "स्पॉटिफाई": "Spotify", "स्पोटिफाई": "Spotify",
    "calculator": "Calculator", "कैलकुलेटर": "Calculator", "mail": "Mail", "मेल": "Mail",
    "calendar": "Calendar", "कैलेंडर": "Calendar", "whatsapp": "WhatsApp", "व्हाट्सएप": "WhatsApp",
    "व्हाट्सऐप": "WhatsApp", "messages": "Messages", "मैसेज": "Messages", "xcode": "Xcode",
    "एक्सकोड": "Xcode", "photos": "Photos", "फोटोज": "Photos", "फोटो": "Photos",
    "settings": "System Settings", "system settings": "System Settings", "सेटिंग्स": "System Settings",
    "सेटिंग": "System Settings", "slack": "Slack", "स्लैक": "Slack", "zoom": "zoom.us",
    "ज़ूम": "zoom.us", "जूम": "zoom.us", "lightroom": "Adobe Lightroom Classic",
    "लाइटरूम": "Adobe Lightroom Classic", "photoshop": "Adobe Photoshop 2025",
    "फोटोशॉप": "Adobe Photoshop 2025", "figma": "Figma", "फिग्मा": "Figma",
    "youtube": "__url__https://www.youtube.com", "यूट्यूब": "__url__https://www.youtube.com",
    "gmail": "__url__https://mail.google.com", "जीमेल": "__url__https://mail.google.com",
}

FOLDERS = {
    "desktop": HOME / "Desktop", "डेस्कटॉप": HOME / "Desktop",
    "documents": HOME / "Documents", "डॉक्यूमेंट्स": HOME / "Documents", "डॉक्युमेंट्स": HOME / "Documents",
    "downloads": HOME / "Downloads", "डाउनलोड्स": HOME / "Downloads", "डाउनलोड": HOME / "Downloads",
    "pictures": HOME / "Pictures", "पिक्चर्स": HOME / "Pictures", "home": HOME,
}


# ---------- primitives ----------
def _esc(s: str) -> str:
    """Escape a string for inclusion inside an AppleScript string literal."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def osascript(script: str, timeout: int = 20) -> tuple[bool, str]:
    try:
        p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return False, "osascript not available (not macOS)"
    except subprocess.TimeoutExpired:
        return False, "AppleScript timed out"


def _run(cmd: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return False, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return False, "command timed out"


def resolve_app(name: str) -> str:
    key = (name or "").strip().lower().strip(".।!?")
    return APP_ALIASES.get(key, name.strip())


# ---------- apps ----------
def open_app(name: str) -> str:
    app = resolve_app(name)
    if app.startswith("__url__"):
        return open_url(app[len("__url__"):])
    ok, out = _run(["open", "-a", app])
    if ok:
        return f"Opened {app}."
    # fuzzy: ask Spotlight for an application whose name contains the words
    ok2, found = _run(["mdfind", f'kMDItemContentType == "com.apple.application-bundle" && kMDItemDisplayName == "*{app}*"cd'])
    candidates = [line for line in found.splitlines() if line.endswith(".app")] if ok2 else []
    if candidates:
        candidates.sort(key=len)
        ok3, _ = _run(["open", candidates[0]])
        if ok3:
            return f"Opened {Path(candidates[0]).stem}."
    return f"I couldn't find an app called {name}."


def quit_app(name: str) -> str:
    app = resolve_app(name)
    ok, out = osascript(f'tell application "{_esc(app)}" to quit')
    return f"Closed {app}." if ok else f"Couldn't close {app}: {out}"


def list_running_apps() -> str:
    ok, out = osascript('tell application "System Events" to get name of every application process whose background only is false')
    return f"Running apps: {out}." if ok else f"Couldn't list apps: {out}"


# ---------- web ----------
def open_url(url: str) -> str:
    if not re.match(r"^[a-z]+://", url):
        url = "https://" + url
    ok, out = _run(["open", url])
    return f"Opened {url}." if ok else f"Couldn't open {url}: {out}"


def web_search(query: str) -> str:
    open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Searched Google for {query}."


def youtube_search(query: str) -> str:
    open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
    return f"Opened YouTube results for {query}."


# ---------- volume / media ----------
def get_volume() -> int:
    ok, out = osascript("output volume of (get volume settings)")
    try:
        return int(out)
    except ValueError:
        return -1


def set_volume(level: int) -> str:
    level = max(0, min(100, int(level)))
    ok, out = osascript(f"set volume output volume {level}")
    return f"Volume set to {level} percent." if ok else f"Couldn't set volume: {out}"


def change_volume(delta: int) -> str:
    cur = get_volume()
    if cur < 0:
        return "Couldn't read the volume."
    return set_volume(cur + int(delta))


def mute(on: bool = True) -> str:
    ok, out = osascript(f"set volume output muted {'true' if on else 'false'}")
    return ("Muted." if on else "Unmuted.") if ok else f"Couldn't change mute: {out}"


def media_control(command: str, app: str = "") -> str:
    """command: play | pause | playpause | next | previous"""
    command = command.lower()
    verbs = {"play": "play", "pause": "pause", "playpause": "playpause",
             "next": "next track", "previous": "previous track"}
    verb = verbs.get(command)
    if not verb:
        return f"Unknown media command {command}."
    targets = [resolve_app(app)] if app else ["Spotify", "Music"]
    for target in targets:
        _ok, state = osascript(f'if application "{_esc(target)}" is running then return "yes"')
        if state == "yes" or app:
            ok, out = osascript(f'tell application "{_esc(target)}" to {verb}')
            if ok:
                return f"{target}: {command}."
    ok, out = osascript(f'tell application "Music" to {verb}')
    return f"Music: {command}." if ok else f"Couldn't control media: {out}"


# ---------- system info ----------
def get_time() -> str:
    return datetime.now().strftime("It's %I:%M %p.").replace(" 0", " ")


def get_date() -> str:
    return datetime.now().strftime("Today is %A, %d %B %Y.")


def get_battery() -> str:
    ok, out = _run(["pmset", "-g", "batt"])
    if not ok:
        return "Couldn't read the battery."
    m = re.search(r"(\d+)%;\s*([^;]+);", out)
    if not m:
        return "This Mac doesn't seem to have a battery."
    return f"Battery is at {m.group(1)} percent, {m.group(2).strip()}."


def system_status() -> str:
    parts = []
    try:
        import psutil
        parts.append(f"CPU {psutil.cpu_percent(interval=0.5):.0f} percent")
        vm = psutil.virtual_memory()
        parts.append(f"memory {vm.percent:.0f} percent used")
    except ImportError:
        pass
    du = shutil.disk_usage("/")
    parts.append(f"{du.free / 1e9:.0f} gigabytes free on disk")
    bat = get_battery()
    if bat.startswith("Battery"):
        parts.append(bat.rstrip(".").lower())
    return "System status: " + ", ".join(parts) + "."


# ---------- files ----------
def find_files(query: str, folder: str = "", limit: int = 5) -> str:
    cmd = ["mdfind", "-name", query]
    if folder:
        path = FOLDERS.get(folder.lower(), Path(os.path.expanduser(folder)))
        cmd[1:1] = ["-onlyin", str(path)]
    ok, out = _run(cmd, timeout=15)
    hits = [h for h in out.splitlines() if h and "/Library/" not in h][:limit] if ok else []
    if not hits:
        return f"No files matching {query}."
    return "Found: " + "; ".join(hits)


def open_path(path: str) -> str:
    p = FOLDERS.get(path.strip().lower()) or Path(os.path.expanduser(path))
    if not p.exists():
        return f"{path} doesn't exist."
    ok, out = _run(["open", str(p)])
    return f"Opened {p.name or p}." if ok else f"Couldn't open {p}: {out}"


def create_folder(path: str) -> str:
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = HOME / "Desktop" / p
    p.mkdir(parents=True, exist_ok=True)
    return f"Created folder {p}."


def move_to_trash(path: str) -> str:
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return f"{path} doesn't exist."
    ok, out = osascript(f'tell application "Finder" to delete POSIX file "{_esc(str(p))}"')
    return f"Moved {p.name} to the Trash." if ok else f"Couldn't trash it: {out}"


# ---------- keyboard / clipboard ----------
_KEYCODES = {"return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
             "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126}


def type_text(text: str) -> str:
    ok, out = osascript(f'tell application "System Events" to keystroke "{_esc(text)}"')
    return "Typed it." if ok else f"Couldn't type (grant Accessibility access): {out}"


def press_keys(shortcut: str) -> str:
    """e.g. 'cmd+shift+4', 'return', 'cmd+t'"""
    parts = [p.strip().lower() for p in shortcut.replace("-", "+").split("+") if p.strip()]
    mods_map = {"cmd": "command down", "command": "command down", "shift": "shift down",
                "option": "option down", "alt": "option down", "ctrl": "control down", "control": "control down"}
    mods = [mods_map[p] for p in parts if p in mods_map]
    keys = [p for p in parts if p not in mods_map]
    if len(keys) != 1:
        return f"Invalid shortcut {shortcut}."
    key = keys[0]
    using = f" using {{{', '.join(mods)}}}" if mods else ""
    if key in _KEYCODES:
        script = f'tell application "System Events" to key code {_KEYCODES[key]}{using}'
    else:
        script = f'tell application "System Events" to keystroke "{_esc(key)}"{using}'
    ok, out = osascript(script)
    return f"Pressed {shortcut}." if ok else f"Couldn't press keys: {out}"


def get_clipboard() -> str:
    ok, out = _run(["pbpaste"])
    return f"Clipboard: {out[:500]}" if out else "The clipboard is empty."


def set_clipboard(text: str) -> str:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
        return "Copied to clipboard."
    except Exception as e:
        return f"Couldn't copy: {e}"


# ---------- misc ----------
def take_screenshot() -> str:
    path = HOME / "Desktop" / f"Friday Screenshot {datetime.now():%Y-%m-%d at %H.%M.%S}.png"
    ok, out = _run(["screencapture", "-x", str(path)])
    return f"Screenshot saved to your Desktop." if ok else f"Couldn't take a screenshot: {out}"


def lock_screen() -> str:
    ok, out = _run(["pmset", "displaysleepnow"])
    return "Locking the screen." if ok else f"Couldn't lock: {out}"


def toggle_dark_mode() -> str:
    ok, out = osascript('tell application "System Events" to tell appearance preferences to set dark mode to not dark mode')
    return "Toggled dark mode." if ok else f"Couldn't toggle dark mode: {out}"


def send_email(to: str, subject: str, body: str) -> str:
    script = f'''
tell application "Mail"
    set m to make new outgoing message with properties {{subject:"{_esc(subject)}", content:"{_esc(body)}", visible:false}}
    tell m to make new to recipient at end of to recipients with properties {{address:"{_esc(to)}"}}
    send m
end tell'''
    ok, out = osascript(script, timeout=40)
    return f"Email sent to {to}." if ok else f"Couldn't send the email: {out}"


def run_shell(command: str) -> str:
    ok, out = _run(["/bin/zsh", "-lc", command], timeout=60)
    out = out[-1500:] if out else "(no output)"
    return ("Command finished. " if ok else "Command failed. ") + out
