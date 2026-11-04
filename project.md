# Friday for macOS — हिंदी + English voice assistant 🎙️

A real Mac app (`Friday.app`) with a floating arc-reactor orb, a menu-bar icon, and an
`⌥J` hotkey. Speak in **English, Hindi (हिंदी) or Hinglish**. Friday understands you
locally, acts on your Mac, and answers **in the same language** with a neural voice.

```
"Friday, open Chrome"                  → Opening Google Chrome.
"फ्राइडे, यूट्यूब पर अरिजीत सिंह के गाने चलाओ"    → यूट्यूब पर अरिजीत सिंह के गाने लगा दिया।
"Friday volume kam karo"               → आवाज़ 40 प्रतिशत कर दी।
"Friday, how's my Mac doing?"          → Running smoothly, sir — CPU at 12 percent…
"फ्राइडे, डाउनलोड्स में invoice वाली PDF ढूँढो"   → (local AI picks find_files and answers in Hindi)
```

## Install (about 10 minutes, mostly downloads)

```bash
cd jarvis-mac
chmod +x setup.sh build_app.sh
./setup.sh              # add --login to start Friday at login
```

`setup.sh` creates the venv, installs Ollama and pulls the local model (`qwen2.5:7b`,
~4.7 GB), downloads the Whisper `small` speech model (~480 MB), caches the voice lines,
and installs **Friday.app** into `/Applications`. Then open Friday from Spotlight.

**On first launch, allow:** Microphone · Accessibility + Input Monitoring (System
Settings → Privacy & Security → add Friday) for the hotkey and typing · the one-time
Automation pop-ups for Chrome, Mail and Music.

## How it works

```
🎤 mic ─► Whisper small (local)  ─► Hindi / English detected
                                     │
              ┌──────────────────────┴───────────────────────┐
     fast command engine (instant)               local LLM via Ollama (offline)
     open/close apps, volume, time, battery,     anything else: multi-step tasks,
     YouTube, Google, music, screenshot          questions, email, files, shell
              └──────────────────────┬───────────────────────┘
                          macOS actions (AppleScript / shell)
                                     │
        🔊 neural voice: en-GB-RyanNeural (English) · hi-IN-MadhurNeural (हिंदी)
           offline fallback: macOS Daniel / Lekha
```

| Piece | Offline? |
|---|---|
| Speech recognition (Whisper) | ✅ fully local |
| Thinking (Ollama + Qwen 2.5) | ✅ fully local |
| Quick commands | ✅ work even without Ollama |
| Voice | Neural voices need internet; clips are cached, and Friday falls back to the macOS voices when offline |

## Using it

- **Wake word:** say "Friday …" / "फ्राइडे …", either in one breath ("Friday, open Notes") or on its own and wait for "जी सर?" / "Yes, sir?".
- **Push-to-talk:** click the orb, press `⌥J` anywhere, or press Space while the window is focused.
- **Follow-ups:** after Friday replies, the mic stays open for about 8 seconds, so you don't need to say the wake word again.
- **Type instead:** use the input box (English or Hindi).
- **Stop:** press `Esc`, or say "stop" / "रुको". Say "stop listening" / "सो जाओ" to turn the mic off. Say "goodbye" / "अलविदा" to quit.
- **Language chip** (`AUTO / EN / हिं`): Auto detects the language each time. Lock it to हिं if Hindi is mis-detected in a noisy room.
- **Safety:** sending email, running shell commands, and trashing files always ask first. Answer by voice ("haan" / "नहीं") or with the buttons.

## Tuning (`.env`)

| Problem | Fix |
|---|---|
| Hindi transcribed badly | `WHISPER_MODEL=medium` (slower, much better Hindi) |
| Replies slow | `JARVIS_LOCAL_MODEL=qwen2.5:3b` |
| Better Hindi answers | `JARVIS_LOCAL_MODEL=qwen2.5:14b` (needs 32 GB RAM) |
| Recording never stops / cuts off | raise / lower `SILENCE_THRESHOLD` (`python debug_audio.py` shows your levels) |
| Friday hears "Friday" by accident | `JARVIS_WAKE_WORD=false` (orb / ⌥J only) |
| Different voice | `edge-tts --list-voices`, then set `JARVIS_VOICE_EN` / `JARVIS_VOICE_HI` |

Logs: `~/Library/Application Support/Friday/` (menu bar → *Open settings & logs folder*).
Terminal mode for debugging: `./venv/bin/python main.py`. Tests: `python tests/test_core.py && python tests/test_flow.py`.

> About the voice: Ryan (British male, slightly lowered pitch) is the default stock voice. You can change it with `JARVIS_VOICE_PITCH` / `JARVIS_VOICE_RATE`.
