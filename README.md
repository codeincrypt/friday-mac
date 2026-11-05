# Friday for macOS 🎙️

**A Hindi + English voice assistant for your Mac. It runs on your machine, listens for "Friday" (or "फ्राइडे"), does things on your Mac, and talks back in the language you spoke.**

---

## What is Friday?

Friday is a Mac app with a floating orb window, a menu-bar icon and a global hotkey (`⌥J`). You speak, or type, in **English, Hindi (हिंदी) or Hinglish**. Friday:

1. **Hears you** with Whisper speech recognition, running locally.
2. **Understands you** with a local AI model (Ollama + Qwen 2.5), so it works offline.
3. **Acts on your Mac** through AppleScript and shell actions.
4. **Answers out loud** in the same language as your request, using a neural voice.

```
"Friday, open Chrome"                       → Opening Google Chrome.
"फ्राइडे, यूट्यूब पर अरिजीत सिंह के गाने चलाओ"    → यूट्यूब पर अरिजीत सिंह के गाने लगा दिया।
"Friday, volume kam karo"                   → आवाज़ 40 प्रतिशत कर दी।
"Friday, how's my Mac doing?"               → Running smoothly, sir. CPU at 12 percent.
"फ्राइडे, डाउनलोड्स में invoice वाली PDF ढूँढो"    → (the local AI finds the file and replies in Hindi)
```

## Use cases

| Category | Examples |
|---|---|
| **Apps** | Open or quit any app, list what is running |
| **Web** | Google something, search YouTube, open a URL |
| **Music and media** | Play, pause, next, previous, mute |
| **Volume and system** | Set volume, check battery, CPU and memory, toggle dark mode, lock the screen |
| **Files** | Find files ("the invoice PDF in Downloads"), open a path, create a folder, move to Trash |
| **Typing and shortcuts** | Type text, press key combinations, read or set the clipboard |
| **Screenshots** | Take a screenshot |
| **Email** | Draft and send email (asks first) |
| **Questions and chat** | Time, date, general questions, multi-step tasks, answered by the local AI |
| **Terminal** | Run a shell command (asks first) |

Simple commands such as open an app, volume, time and battery are handled by a fast rule-based engine, so they are instant and work even when Ollama isn't running. Everything else goes to the local AI.

## Requirements

**Hardware and OS**
- A Mac, ideally **Apple Silicon (M1 or later)**, running macOS
- **16 GB RAM** recommended for the default model (8 GB works with a smaller model, 32 GB or more for the best Hindi)
- About **6 GB of free disk space** for models
- A microphone

**Software (the installer sets these up for you)**
- **Python 3.10 or newer**
- **[Homebrew](https://brew.sh)** (optional, but used to auto-install Python and Ollama)
- **[Ollama](https://ollama.com)**, which runs the local AI model
- Python packages from [requirements.txt](requirements.txt): `faster-whisper`, `sounddevice`, `numpy`, `python-dotenv`, `edge-tts`, `pywebview`, `psutil`, `pyobjc`

**Downloaded on first install**
- Local AI model `qwen2.5:7b` (about 4.7 GB)
- Whisper `small` speech model (about 480 MB)

**Internet** is needed only for the initial downloads and for the neural voices. Voice clips are cached, and Friday falls back to the built-in macOS voices when offline.

## Installation

```bash
git clone <your-repo-url> jarvis-mac    # or download and unzip the project
cd jarvis-mac
chmod +x setup.sh build_app.sh
./setup.sh                              # add --login to start Friday at login
```

This takes about 10 minutes, mostly downloads. `setup.sh` will:

1. Find or install Python 3.10+
2. Create a virtual environment and install the dependencies
3. Create your `.env` settings file from `.env.example`
4. Install Ollama and pull the local model
5. Download the Whisper speech model
6. Cache Friday's voice lines
7. Build **Friday.app** and install it into `/Applications`

When it finishes, open **Friday** from Spotlight.

### First-run setup window (new Mac)

The first time Friday opens on a Mac, it shows a **setup window** instead of the orb. One click on **Install everything** does the rest, with live progress:

1. **Local AI engine** – downloads and starts Ollama (skipped if it is already installed)
2. **Friday's brain** – pulls a qwen2.5 model sized for this Mac's RAM (3b / 7b / 14b; you can change the choice)
3. **Speech recognition** – downloads the Whisper model
4. **Friday's voice** – records the neural voice lines (optional; needs internet)
5. **Microphone** and **Accessibility** permissions – with buttons that open the right System Settings pane, and "Skip for now"

Every step checks what is already there, so re-running is quick, and a failed download resumes where it stopped. When it is done, press **Start Friday**. To run it again, use the menu-bar icon → Settings → **Run setup again…**.

This is also the install path for the standalone app: copy `Friday.app` from the DMG to a new laptop, open it, and the window above installs the local AI. The wizard writes the chosen model to `~/Library/Application Support/Friday/.env`.

### Permissions on first launch

macOS will ask for these. Allow them for Friday:

| Permission | Why | Where |
|---|---|---|
| **Microphone** | To hear you | Prompt on first launch |
| **Accessibility** | typing and key presses (the `⌥J` hotkey needs no permission) | System Settings → Privacy & Security → add Friday |
| **Automation** (Chrome, Mail, Music) | To control those apps | One-time pop-ups, click OK |

### Optional: self-contained app and DMG

```bash
./build_standalone.sh
```

This bundles Python and the dependencies into `dist/standalone/Friday.app` and `dist/Friday-standalone.dmg`. Ollama and the models are installed by the first-run setup window on the new Mac.

## How to use

- **Wake word:** say "Friday …" or "फ्राइडे …". Either say it all at once ("Friday, open Notes"), or say just the name and wait for "Yes, sir?" / "जी सर?".
- **Push-to-talk:** click the orb, press `⌥J` from anywhere, or press Space while the window is focused.
- **Follow-ups:** after Friday replies, the mic stays open for about 8 seconds, so you don't need to repeat the wake word.
- **Type instead:** use the input box, in English or Hindi.
- **Stop speaking:** press `Esc`, or say "stop" / "रुको".
- **Mute the mic:** say "stop listening" / "सो जाओ".
- **Quit:** say "goodbye" / "अलविदा".
- **Language chip** (`AUTO / EN / हिं`): Auto detects the language each time. Lock it to हिं if Hindi is mis-detected in a noisy room.
- **Safety:** Friday always asks before sending email, running shell commands or trashing files. It also asks before typing into a terminal, pressing Cmd+Q / Cmd+Delete, or opening an app or script file. It only opens web links, and only creates folders inside your home folder. Answer by voice ("haan" / "नहीं") or with the on-screen buttons.

## Configuration

Settings live in `.env` (see [.env.example](.env.example)). Common fixes:

| Problem | Fix |
|---|---|
| Hindi is transcribed badly | `WHISPER_MODEL=medium` (slower, much better Hindi) |
| Replies are slow | `JARVIS_LOCAL_MODEL=qwen2.5:3b` |
| You want better Hindi answers | `JARVIS_LOCAL_MODEL=qwen2.5:14b` (needs 32 GB RAM) |
| Recording never stops, or cuts you off | Raise or lower `SILENCE_THRESHOLD` (`python debug_audio.py` shows your mic levels) |
| Friday reacts to the word "Friday" by accident | `JARVIS_WAKE_WORD=false` (use the orb or `⌥J` only) |
| Friday "hears" things nobody said, or wakes on noise | Raise `MIN_SPEECH_SECONDS` (e.g. `0.4`) and `SILENCE_THRESHOLD`; use a headset or external mic; try `WHISPER_MODEL=medium` |
| Friday misses you in a quiet room | Lower `SILENCE_THRESHOLD` (e.g. `0.008`). The threshold already rises on its own in noisy rooms (`JARVIS_ADAPTIVE_NOISE`) |
| Friday hears its own voice | Raise `POST_SPEAK_PAUSE` (e.g. `0.6`), or use headphones |
| Answers sound invented | `JARVIS_TEMPERATURE=0`; a bigger model (`qwen2.5:14b`) follows instructions better |
| The log or voice cache is too big | Logs rotate at 1 MB; the voice cache is capped by `JARVIS_CACHE_MAX_MB` (default 50) |
| You want a different voice | Run `edge-tts --list-voices`, then set `JARVIS_VOICE_EN` / `JARVIS_VOICE_HI` |

## Troubleshooting

- **Logs:** `~/Library/Application Support/Friday/` (menu bar → *Open settings & logs folder*). Friday does not log what you say or the text of emails and typed text. For debugging, set `JARVIS_LOG_TRANSCRIPTS=true`.
- **Hotkey does nothing:** another app may already own `⌥J` (check `~/Library/Application Support/Friday/friday.log`); pick another with `JARVIS_HOTKEY=cmd+shift+space`.
- **No response to your voice:** check the Microphone permission, then run `python debug_audio.py`.
- **Slow or no AI answers:** make sure Ollama is running (`ollama list`) and the model is pulled.
- **Run in the terminal for debugging:** `./venv/bin/python main.py`

## Development

```bash
./venv/bin/python tests/test_core.py && ./venv/bin/python tests/test_flow.py && ./venv/bin/python tests/test_setup.py
```

Architecture, project rules and the roadmap are in [project.md](project.md) and [CLAUDE.md](CLAUDE.md).

> **Note:** The automated tests (unit, flow and setup) pass, but they use a fake microphone and a fake Ollama. Real rooms differ: expect to tune `SILENCE_THRESHOLD` and to grant the permissions above on first launch.
