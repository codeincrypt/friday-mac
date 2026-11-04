#!/usr/bin/env python3
"""Terminal mode — same assistant, no window. Useful for debugging:
    python main.py
Say "Friday …" / "फ्राइडे …". Ctrl+C to exit. Type a command and press
Enter at any time to send it as text.
"""
import logging
import os
import sys
import threading

from jarvis import config
from jarvis.assistant import Assistant, Callbacks

logging.basicConfig(level=logging.INFO if os.getenv("JARVIS_DEBUG") else logging.WARNING,
                    format="%(name)s: %(message)s")


class TerminalUI(Callbacks):
    def state(self, state, detail=""):
        icons = {"wake": "👂", "listening": "🎙 ", "thinking": "🧠", "executing": "⚙️ ",
                 "approval": "⚠️ ", "sleeping": "💤", "error": "❌", "loading": "⏳"}
        if state in icons:
            print(f"{icons[state]} {state}{(' — ' + detail) if detail else ''}")

    def message(self, role, text, lang="en"):
        if role == "user":
            print(f"🗣  You [{lang}]: {text}")
        elif role == "system":
            print(f"ℹ️  {text}")

    def tool(self, name, args):
        print(f"   ↳ {name} {args}")

    def approval(self, description):
        if description:
            print(f"   ⚠️  {config.ASSISTANT_NAME} wants to {description} — say yes/haan or no/nahi")

    def quit(self):
        os._exit(0)


def main():
    a = Assistant(TerminalUI())

    def typed():
        for line in sys.stdin:
            a.submit_text(line)

    threading.Thread(target=typed, daemon=True).start()
    try:
        a.run()
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
