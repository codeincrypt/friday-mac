#!/usr/bin/env python3
"""Friday.app — floating orb window + menu-bar icon + global hotkey.

Launched by Friday.app (see build_app.sh) or directly: `python app.py`.
"""
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from jarvis import config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("jarvis.app")

import webview  # noqa: E402

from jarvis.assistant import Assistant, Callbacks  # noqa: E402

UI_FILE = ROOT / "jarvis" / "ui" / "index.html"


SETTINGS_FILE = config.SUPPORT_DIR / "ui_settings.json"
SETTINGS = {"captions": True}


def _load_settings():
    try:
        SETTINGS.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass


def _save_settings():
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(SETTINGS), encoding="utf-8")
    except Exception as e:
        log.debug("settings not saved: %s", e)


_load_settings()


class WebUI(Callbacks):
    """Pushes assistant events into the web page."""

    def __init__(self):
        self.window = None
        self._last_level = 0.0

    def _js(self, fn: str, *args):
        if not self.window:
            return
        payload = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
        try:
            self.window.evaluate_js(f"window.jarvis && jarvis.{fn}({payload})")
        except Exception as e:
            log.debug("evaluate_js failed: %s", e)

    def state(self, state, detail=""):
        self._js("onState", state, detail)
        set_status_icon(state)

    def message(self, role, text, lang="en"):
        self._js("onMessage", role, text, lang)

    def level(self, rms):
        now = time.time()
        if now - self._last_level > 0.06:  # ~15 fps is plenty
            self._last_level = now
            self._js("onLevel", min(1.0, rms * 12))

    def tool(self, name, args):
        self._js("onTool", name, args)

    def approval(self, description):
        self._js("onApproval", description)

    def quit(self):
        threading.Timer(2.5, _quit).start()


ui = WebUI()
assistant = Assistant(ui)


class Api:
    """Methods callable from JavaScript as window.pywebview.api.<name>()."""

    def listen(self):
        assistant.push_to_talk()

    def stop(self):
        assistant.stop()

    def submit(self, text):
        assistant.submit_text(text)

    def approve(self, ok):
        assistant.answer_approval(bool(ok))

    def toggle_mic(self):
        assistant.toggle_sleep()
        return assistant.sleeping

    def set_language(self, mode):
        assistant.set_language(mode)
        return config.LANGUAGE_MODE

    def get_info(self):
        return {"language": config.LANGUAGE_MODE, "model": config.LOCAL_MODEL,
                "voice_en": config.VOICE_EN, "voice_hi": config.VOICE_HI,
                "hotkey": config.HOTKEY, "sleeping": assistant.sleeping,
                "settings": SETTINGS}

    def set_interactive(self, on):
        """Overlay expanded -> take clicks; collapsed (idle) -> click-through."""
        set_click_through(not on)

    def hide(self):
        ui.window.hide()

    def quit(self):
        _quit()


def _quit():
    assistant.shutdown()
    try:
        ui.window.destroy()
    finally:
        os._exit(0)


# ---------------- native macOS extras (menu bar + hotkey) ----------------
_visible = True


def toggle_window():
    global _visible
    if _visible:
        ui.window.hide()
    else:
        ui.window.show()
    _visible = not _visible


_status_item = None
# (arc colour, dashed-ring colour) per assistant state — same palette as the orb
_ICON_COLORS = {
    "default":  ((0.21, 0.94, 1.00), (0.60, 0.36, 1.00)),
    "approval": ((1.00, 0.71, 0.28), (1.00, 0.54, 0.28)),
    "error":    ((1.00, 0.35, 0.42), (1.00, 0.24, 0.35)),
    "sleeping": ((0.42, 0.48, 0.53), (0.42, 0.48, 0.53)),
}


def make_status_icon(state="default", size=18):
    """Full-colour Friday arc-reactor glyph for the menu bar (not a template
    image, so macOS doesn't flatten it to black/white)."""
    from AppKit import NSBezierPath, NSColor, NSImage
    from Foundation import NSMakeSize

    arc_c, ring_c = _ICON_COLORS.get(state, _ICON_COLORS["default"])

    def draw(rect):
        w = rect.size.width
        c = w / 2
        col = lambda t, a=1.0: NSColor.colorWithSRGBRed_green_blue_alpha_(t[0], t[1], t[2], a)

        def arc(radius, start, end, width, color, dash=None):
            p = NSBezierPath.bezierPath()
            p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                (c, c), radius, start, end)
            p.setLineWidth_(width)
            p.setLineCapStyle_(1)  # round
            if dash:
                p.setLineDash_count_phase_(dash, len(dash), 0)
            color.set()
            p.stroke()

        # four bold outer arcs (the reactor ring)
        for a in (0, 90, 180, 270):
            arc(w * 0.44, a + 12, a + 78, w * 0.095, col(arc_c))
        # dashed inner ring
        arc(w * 0.29, 0, 360, w * 0.055, col(ring_c, 0.9), dash=[w * 0.07, w * 0.07])
        # glowing core: soft halo + bright centre
        halo = NSBezierPath.bezierPathWithOvalInRect_(((c - w * 0.2, c - w * 0.2), (w * 0.4, w * 0.4)))
        col(arc_c, 0.35).set()
        halo.fill()
        core = NSBezierPath.bezierPathWithOvalInRect_(((c - w * 0.11, c - w * 0.11), (w * 0.22, w * 0.22)))
        NSColor.whiteColor().set()
        core.fill()
        return True

    img = NSImage.imageWithSize_flipped_drawingHandler_(NSMakeSize(size, size), False, draw)
    img.setTemplate_(False)
    return img


def set_status_icon(state):
    """Recolour the menu-bar icon for the assistant's state (any thread)."""
    if _status_item is None:
        return
    key = state if state in _ICON_COLORS else "default"
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(lambda: _status_item.button().setImage_(make_status_icon(key)))
    except Exception as e:
        log.debug("status icon update failed: %s", e)


def install_macos_extras():
    """Status-bar menu and a global Option+J hotkey. Optional: any failure
    here only logs, the floating window keeps working."""
    try:
        import objc
        from AppKit import (NSApplication, NSEvent, NSImage, NSMenu, NSMenuItem,
                            NSStatusBar, NSVariableStatusItemLength)
        from Foundation import NSObject
        from PyObjCTools import AppHelper
    except Exception as e:
        log.info("macOS extras unavailable: %s", e)
        return

    def bg(fn):  # never block the Cocoa main thread on pywebview calls
        threading.Thread(target=fn, daemon=True).start()

    def push_settings():
        _save_settings()
        bg(lambda: ui._js("onSettings", SETTINGS))

    def set_lang(mode):
        assistant.set_language(mode)

    _items = {}

    class MenuTarget(NSObject):
        def showHide_(self, _sender):
            bg(toggle_window)

        def listen_(self, _sender):
            assistant.push_to_talk()

        def mic_(self, _sender):
            assistant.toggle_sleep()

        def captions_(self, _sender):
            SETTINGS["captions"] = not SETTINGS["captions"]
            push_settings()

        def lang_(self, sender):
            set_lang({"Auto (हिंदी + English)": "auto", "English": "en", "हिंदी": "hi"}[str(sender.title())])

        def openLog_(self, _sender):
            os.system(f'open "{config.SUPPORT_DIR}"')

        def quit_(self, _sender):
            bg(_quit)

        def menuNeedsUpdate_(self, _menu):  # keep checkmarks in sync (the mic can also change by voice)
            _items["captions"].setState_(1 if SETTINGS["captions"] else 0)
            _items["mic"].setState_(0 if assistant.sleeping else 1)
            for title, mode in (("Auto (हिंदी + English)", "auto"), ("English", "en"), ("हिंदी", "hi")):
                _items["lang:" + mode].setState_(1 if config.LANGUAGE_MODE == mode else 0)

    def build():
        global _status_item, _menu_target, _monitors
        _menu_target = MenuTarget.alloc().init()
        _status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        try:
            _status_item.button().setImage_(make_status_icon())
        except Exception as e:
            log.info("status icon failed (%s); using text fallback", e)
            _status_item.button().setTitle_("◉")

        def add(menu, title, sel, key="", tag=None):
            if title is None:
                menu.addItem_(NSMenuItem.separatorItem())
                return None
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
            item.setTarget_(_menu_target)
            menu.addItem_(item)
            if tag:
                _items[tag] = item
            return item

        def header(menu, title):
            h = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            h.setEnabled_(False)
            menu.addItem_(h)

        # Everything that used to sit on the overlay lives here.
        settings = NSMenu.alloc().init()
        header(settings, "Language")
        add(settings, "Auto (हिंदी + English)", "lang:", tag="lang:auto")
        add(settings, "English", "lang:", tag="lang:en")
        add(settings, "हिंदी", "lang:", tag="lang:hi")
        add(settings, None, None)
        add(settings, "Microphone (listening for “Friday”)", "mic:", tag="mic")
        add(settings, "Show captions", "captions:", tag="captions")
        add(settings, None, None)
        add(settings, "Open settings & logs folder", "openLog:")

        menu = NSMenu.alloc().init()
        menu.setDelegate_(_menu_target)
        settings.setDelegate_(_menu_target)
        add(menu, "Listen now  (⌥J)", "listen:")
        add(menu, "Show / Hide Friday", "showHide:")
        add(menu, None, None)
        sub = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Settings", None, "")
        sub.setSubmenu_(settings)
        menu.addItem_(sub)
        add(menu, None, None)
        add(menu, "Quit Friday", "quit:", "q")
        _status_item.setMenu_(menu)

        # Global hotkey (needs Accessibility / Input Monitoring permission).
        key_mask = 1 << 10                 # NSEventMaskKeyDown
        option_flag = 1 << 19              # NSEventModifierFlagOption
        hot_char = (config.HOTKEY.split("+")[-1] or "j").lower()

        def matches(event):
            try:
                return (event.modifierFlags() & option_flag) and \
                    (event.charactersIgnoringModifiers() or "").lower() == hot_char
            except Exception:
                return False

        def global_handler(event):
            if matches(event):
                assistant.push_to_talk()

        def local_handler(event):
            if matches(event):
                assistant.push_to_talk()
                return None
            return event

        _monitors = [
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(key_mask, global_handler),
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(key_mask, local_handler),
        ]
        log.info("menu bar + hotkey installed")

    AppHelper.callAfter(build)


def _jarvis_windows():
    from AppKit import NSApplication
    # Only our window: the status item also owns an NSWindow.
    return [w for w in NSApplication.sharedApplication().windows() if w.title() == "Friday"]


def make_overlay():
    """Full-screen, see-through HUD above the menu bar, on every Space and over
    full-screen apps. Starts click-through; the page turns clicks on while the
    overlay is expanded (see Api.set_interactive)."""
    try:
        from AppKit import NSColor, NSScreen, NSStatusWindowLevel
        from PyObjCTools import AppHelper
    except Exception as e:
        log.debug("overlay setup skipped: %s", e)
        return

    def apply():
        try:
            for w in _jarvis_windows():
                w.setOpaque_(False)
                w.setBackgroundColor_(NSColor.clearColor())
                w.setHasShadow_(False)
                w.setLevel_(NSStatusWindowLevel)
                # canJoinAllSpaces | stationary | fullScreenAuxiliary
                w.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8))
                screen = w.screen() or NSScreen.mainScreen()
                w.setFrame_display_(screen.frame(), True)  # includes the menu-bar / notch strip
                w.setIgnoresMouseEvents_(True)
        except Exception as e:
            log.debug("overlay apply failed: %s", e)

    AppHelper.callAfter(apply)


def set_click_through(on: bool):
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(lambda: [w.setIgnoresMouseEvents_(bool(on)) for w in _jarvis_windows()])
    except Exception as e:
        log.debug("click-through toggle failed: %s", e)


def boot(window):
    ui.window = window
    install_macos_extras()
    make_overlay()
    threading.Thread(target=assistant.run, name="jarvis-loop", daemon=True).start()


def brand_process():
    """Make the Dock / app menu say "Friday" with our icon instead of "Python"."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Friday"
            info["CFBundleDisplayName"] = "Friday"
        icon = ROOT / "assets" / "icon_1024.png"
        if icon.exists():
            img = NSImage.alloc().initWithContentsOfFile_(str(icon))
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception as e:
        log.debug("branding skipped: %s", e)


def main():
    brand_process()
    try:
        scr = webview.screens[0]
        width, height = int(scr.width), int(scr.height)
    except Exception:
        width, height = 1440, 900
    window = webview.create_window(
        "Friday", url=str(UI_FILE), js_api=Api(),
        x=0, y=0, width=width, height=height, min_size=(320, 420),
        frameless=True, easy_drag=False, on_top=True, transparent=True,
        background_color="#000000",  # ignored by macOS when transparent=True (window is clear)
    )
    webview.start(boot, window, debug=os.getenv("JARVIS_DEBUG") == "1")
    _quit()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # required for the PyInstaller (standalone) build
    main()
