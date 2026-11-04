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

### Permissions on first launch

macOS will ask for these. Allow them for Friday:

| Permission | Why | Where |
|---|---|---|
| **Microphone** | To hear you | Prompt on first launch |
| **Accessibility** and **Input Monitoring** | `⌥J` hotkey, typing, key presses | System Settings → Privacy & Security → add Friday |
| **Automation** (Chrome, Mail, Music) | To control those apps | One-time pop-ups, click OK |

### Optional: self-contained app and DMG

```bash
./build_standalone.sh
```

This bundles Python and the dependencies into `dist/standalone/Friday.app` and `dist/Friday-standalone.dmg`. Ollama and the model are still installed separately.

## How to use

- **Wake word:** say "Friday …" or "फ्राइडे …". Either say it all at once ("Friday, open Notes"), or say just the name and wait for "Yes, sir?" / "जी सर?".
- **Push-to-talk:** click the orb, press `⌥J` from anywhere, or press Space while the window is focused.
- **Follow-ups:** after Friday replies, the mic stays open for about 8 seconds, so you don't need to repeat the wake word.
- **Type instead:** use the input box, in English or Hindi.
- **Stop speaking:** press `Esc`, or say "stop" / "रुको".
- **Mute the mic:** say "stop listening" / "सो जाओ".
- **Quit:** say "goodbye" / "अलविदा".
- **Language chip** (`AUTO / EN / हिं`): Auto detects the language each time. Lock it to हिं if Hindi is mis-detected in a noisy room.
- **Safety:** sending email, running shell commands and trashing files always ask for confirmation. Answer by voice ("haan" / "नहीं") or with the on-screen buttons.

## Configuration

Settings live in `.env` (see [.env.example](.env.example)). Common fixes:

| Problem | Fix |
|---|---|
| Hindi is transcribed badly | `WHISPER_MODEL=medium` (slower, much better Hindi) |
| Replies are slow | `JARVIS_LOCAL_MODEL=qwen2.5:3b` |
| You want better Hindi answers | `JARVIS_LOCAL_MODEL=qwen2.5:14b` (needs 32 GB RAM) |
| Recording never stops, or cuts you off | Raise or lower `SILENCE_THRESHOLD` (`python debug_audio.py` shows your mic levels) |
| Friday reacts to the word "Friday" by accident | `JARVIS_WAKE_WORD=false` (use the orb or `⌥J` only) |
| You want a different voice | Run `edge-tts --list-voices`, then set `JARVIS_VOICE_EN` / `JARVIS_VOICE_HI` |

## Troubleshooting

- **Logs:** `~/Library/Application Support/Friday/` (menu bar → *Open settings & logs folder*).
- **Hotkey does nothing:** grant Input Monitoring and Accessibility to Friday, then restart it.
- **No response to your voice:** check the Microphone permission, then run `python debug_audio.py`.
- **Slow or no AI answers:** make sure Ollama is running (`ollama list`) and the model is pulled.
- **Run in the terminal for debugging:** `./venv/bin/python main.py`

## Development

```bash
python tests/test_core.py && python tests/test_flow.py
```

Architecture, project rules and the roadmap are in [project.md](project.md) and [CLAUDE.md](CLAUDE.md).

> **Note:** Friday has not been fully tested on real macOS hardware yet. Expect some first-run friction with permissions, the hotkey and microphone sensitivity.
