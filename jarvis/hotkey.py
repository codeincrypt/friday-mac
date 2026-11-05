"""Global push-to-talk hotkey.

Uses Carbon's RegisterEventHotKey (via ctypes): unlike an NSEvent global monitor
it *consumes* the key press — so Option+J doesn't type "∆" into the focused app —
and it needs no Input Monitoring permission.

`parse_hotkey("option+j")` is pure Python so it can be tested anywhere.
"""
import ctypes
import logging
from dataclasses import dataclass

log = logging.getLogger("jarvis.hotkey")

# Carbon modifier bits (Events.h) and NSEvent modifier-flag bits
_CARBON_MODS = {"cmd": 0x0100, "shift": 0x0200, "option": 0x0800, "ctrl": 0x1000}
_NS_MODS = {"cmd": 1 << 20, "shift": 1 << 17, "option": 1 << 19, "ctrl": 1 << 18}
_MOD_NAMES = {"cmd": "cmd", "command": "cmd", "⌘": "cmd", "shift": "shift", "⇧": "shift",
              "option": "option", "opt": "option", "alt": "option", "⌥": "option",
              "ctrl": "ctrl", "control": "ctrl", "⌃": "ctrl"}

# ANSI virtual key codes (physical key positions, independent of keyboard layout)
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
    "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
    "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35,
    "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "return": 36, "enter": 36, "tab": 48, "space": 49, "escape": 53, "esc": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}


@dataclass(frozen=True)
class Hotkey:
    carbon_mods: int   # for RegisterEventHotKey
    ns_flags: int      # for the NSEvent fallback
    keycode: int
    key: str           # normalised key name, e.g. "j"
    label: str         # human readable, e.g. "option+j"


_SYMBOLS = {"cmd": "⌘", "shift": "⇧", "option": "⌥", "ctrl": "⌃"}


def pretty(hk: "Hotkey") -> str:
    """Hotkey as shown in the menu: option+j -> ⌥J."""
    return "".join(_SYMBOLS.get(p, p.upper() if len(p) == 1 else p.capitalize()) for p in hk.label.split("+"))


def parse_hotkey(spec: str) -> Hotkey:
    """'option+j', 'cmd+shift+space', 'ctrl+option+f5' -> Hotkey. Raises ValueError."""
    parts = [p.strip().lower() for p in (spec or "").replace(" ", "").split("+") if p.strip()]
    mods, keys = [], []
    for p in parts:
        (mods if p in _MOD_NAMES else keys).append(_MOD_NAMES.get(p, p))
    if len(keys) != 1:
        raise ValueError(f"hotkey {spec!r} needs exactly one non-modifier key")
    key = keys[0]
    if key not in KEYCODES:
        raise ValueError(f"unsupported hotkey key {key!r}")
    if not mods and not (key.startswith("f") and key[1:].isdigit()):   # bare F-keys are fine
        raise ValueError("hotkey needs at least one modifier (option, cmd, ctrl, shift)")
    mods = sorted(set(mods))
    return Hotkey(carbon_mods=sum(_CARBON_MODS[m] for m in mods),
                  ns_flags=sum(_NS_MODS[m] for m in mods),
                  keycode=KEYCODES[key], key=key, label="+".join(mods + [key]))


def parse_or_default(spec: str, default: str = "option+j") -> Hotkey:
    try:
        return parse_hotkey(spec)
    except ValueError as e:
        log.warning("%s — falling back to %s", e, default)
        return parse_hotkey(default)


# ---------------------------------------------------------------- Carbon bridge
class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_K_EVENT_CLASS_KEYBOARD = 0x6B657962      # 'keyb'
_K_EVENT_HOTKEY_PRESSED = 5
_SIGNATURE = 0x46524459                   # 'FRDY'


class CarbonHotkey:
    """Registers one system-wide hotkey. Call register() on the Cocoa main thread;
    `callback` is then invoked on the main thread each time the key is pressed."""

    def __init__(self, hotkey: Hotkey, callback):
        self.hotkey = hotkey
        self._callback = callback
        self._carbon = None
        self._ref = ctypes.c_void_p()
        self._handler_ref = ctypes.c_void_p()
        self._c_handler = None            # must stay referenced or ctypes frees the trampoline

    def register(self) -> bool:
        try:
            c = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            c.GetApplicationEventTarget.restype = ctypes.c_void_p
            c.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_uint32,
                                              ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_void_p)]
            c.InstallEventHandler.restype = ctypes.c_int32
            c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                              ctypes.c_void_p, ctypes.c_uint32,
                                              ctypes.POINTER(ctypes.c_void_p)]
            c.RegisterEventHotKey.restype = ctypes.c_int32
            c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
            c.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        except (OSError, AttributeError) as e:
            log.info("Carbon hotkeys unavailable: %s", e)
            return False

        def on_event(_call_ref, _event, _user_data):
            try:
                self._callback()
            except Exception:
                log.exception("hotkey callback failed")
            return 0

        self._c_handler = _HANDLER(on_event)
        spec = _EventTypeSpec(_K_EVENT_CLASS_KEYBOARD, _K_EVENT_HOTKEY_PRESSED)
        target = c.GetApplicationEventTarget()
        rc = c.InstallEventHandler(target, self._c_handler, 1, ctypes.byref(spec), None,
                                   ctypes.byref(self._handler_ref))
        if rc != 0:
            log.warning("InstallEventHandler failed (%s)", rc)
            return False
        rc = c.RegisterEventHotKey(self.hotkey.keycode, self.hotkey.carbon_mods,
                                   _EventHotKeyID(_SIGNATURE, 1), target, 0, ctypes.byref(self._ref))
        if rc != 0:   # -9878 = already taken by another app
            log.warning("RegisterEventHotKey(%s) failed (%s) — is another app using it?",
                        self.hotkey.label, rc)
            c.RemoveEventHandler(self._handler_ref)
            return False
        self._carbon = c
        return True

    def unregister(self) -> None:
        if self._carbon and self._ref:
            self._carbon.UnregisterEventHotKey(self._ref)
            self._carbon.RemoveEventHandler(self._handler_ref)
            self._carbon = None
