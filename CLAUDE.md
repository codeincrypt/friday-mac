# CLAUDE.md — Friday for macOS (v2: bilingual Mac app)

The app was renamed Jarvis → **Friday**. The wake word is "Friday" / "फ्राइडे". The Python package (`jarvis/`), the `JARVIS_*` env vars and the JS `window.jarvis` bridge keep the old name on purpose, so existing `.env` files and imports still work.

Context file for Claude Code. v2 replaces the v1 terminal assistant (Claude/HF
backends, English only) with a **Mac app**, **Hindi + English**, and an **offline local brain**.

## Architecture (keep these boundaries)

| File | Role |
|---|---|
| `app.py` | Mac app: pywebview floating window, JS API, NSStatusItem menu, global hotkey (Carbon via `jarvis/hotkey.py`), Dock branding |
| `main.py` | Terminal runner of the same Assistant (debugging) |
| `jarvis/assistant.py` | UI-agnostic state machine: wake word → listen → fast command or LLM → speak; approvals; follow-ups |
| `jarvis/listen.py` | sounddevice capture + RMS silence detection; faster-whisper with hi/en-only detection (Urdu/related probs fold into Hindi); wake word matched only at the start of an utterance or after a comma ("Friday" is also a weekday); wake loop uses a quick English-only gate (`listen(wake_gate=True)`), language ID via `detect_language()` |
| `jarvis/lang.py` | Devanagari / Hinglish / English detection of text |
| `jarvis/commands.py` | Deterministic bilingual fast-command parser + Hindi reply templates (works without Ollama) |
| `jarvis/brain.py` | Ollama `/api/chat` tool loop (stdlib urllib), text-tool-call fallback, history trim |
| `jarvis/toolbox.py` | **Single source of truth for tools**: schemas, arg validation/coercion, NEEDS_CONFIRMATION |
| `jarvis/actions.py` | AppleScript/shell actions; `APP_ALIASES` maps Hindi/Hinglish app names |
| `jarvis/speak.py` | edge-tts neural voices (Ryan / Madhur), disk cache, `say` fallback, interruptible; replies are split into sentences, synthesised in parallel and played as each is ready |
| `jarvis/onboarding.py` + `jarvis/ui/setup.html` | First-run setup wizard (own normal window, shown until `setup.json` exists in the support dir): installs/starts Ollama, pulls the RAM-sized model, downloads Whisper, caches voices, walks through mic/Accessibility permissions. UI-agnostic `Setup` class with per-step checks (idempotent), tested in `tests/test_setup.py` against a fake Ollama |
| `jarvis/phrases.py` | Friday signature lines in both languages |
| `jarvis/prompts.py` | System prompt: reply in the `[lang=xx]` tag language, Devanagari for Hindi, 1–2 spoken sentences |
| `jarvis/ui/index.html` | Orb UI; Python → JS via `jarvis.onState/onMessage/onLevel/onTool/onApproval/onLanguage` |
| `build_app.sh` / `setup.sh` | Bundle builder (bash launcher `exec`s venv python; ad-hoc codesign) / installer |

## Rules
- Add a tool: schema in `toolbox.TOOLS`, function in `actions.py`, mapping in `_FUNCS` (an assert checks they match). Destructive → `NEEDS_CONFIRMATION`.
- Fast-command phrases go in `commands.parse` **and** get a test case in `tests/test_core.py::CASES` plus a Hindi template in `respond()`.
- Keyword intents (battery, screenshot, dark mode, lock, goodbye, status) must be *command-shaped*: guard them with `commands._only(t, vocab)` so a sentence that merely contains the keyword falls through to the LLM. Add the false-positive sentence to `tests/test_core.py::NOT_COMMANDS`.
- Tools that are dangerous only in some contexts (typing into a terminal, Cmd+Q, opening an .app) are gated in `toolbox.needs_confirmation`, not by blanket `NEEDS_CONFIRMATION`. `open_url` only allows safe schemes; `create_folder` stays inside `$HOME`.
- Never log email bodies, typed text, clipboard contents or transcripts (see `toolbox.loggable`, `JARVIS_LOG_TRANSCRIPTS`).
- Whisper `initial_prompt` must stay a vocabulary list, never sentences a user could say (it gets echoed on noise). Every transcript passes `segment_ok` (confidence) and `_is_hallucination` before use; add new junk phrases to `_HALLUCINATIONS`, but never words approval/commands rely on ("ok", "yes", "stop").
- Keep `without_timestamps=True` in every Whisper `transcribe` call: timestamp decoding made Hindi take 5–10 s instead of ~2 s (measured on M5, `small`, beam 5). The wake gate drops clips with no speech via VAD first, tries Hindi if the English pass misses a Hindi-sounding clip, and logs rejections at INFO (no text unless `JARVIS_LOG_TRANSCRIPTS`).
- Compound requests ("and", "और", "phir") must fall through to the LLM.
- Every user message to the LLM is prefixed `[lang=hi|en]`; replies must stay speakable (no markdown).
- Never block the Cocoa main thread with pywebview calls (menu handlers use `bg()`).
- Keep `.env.example` in sync with `config.py`.
- Setup steps: add to `onboarding.STEPS` + a `_step_<id>` method that first checks "already done". Required steps raise `SetupError(msg, hint, actions)`; optional ones may be skipped. The wizard only opens the whitelisted Settings panes / URLs in `onboarding.open_settings/open_url`. After the wizard finishes, `app.py` re-`exec`s itself so `config` reloads the model it wrote to the support-dir `.env`.

## Status
- Unit, flow and setup tests pass (`tests/test_core.py`, `tests/test_flow.py`, `tests/test_setup.py`) with a fake Ollama, a scripted mic and a fake `sounddevice`. Run them with `./venv/bin/python` (plain `python3` lacks numpy). The real Whisper model was also checked on silence/noise/`say`-generated speech.
- **Not yet run on real macOS.** Expect first-run friction with TCC permissions (mic attribution through the bash launcher), the global hotkey (Carbon registration is verified, but firing is untested in the live app), pywebview transparency, and `SILENCE_THRESHOLD`.

## Roadmap
1. Porcupine/openWakeWord instead of Whisper-based wake detection (lower CPU)
2. Streaming TTS (speak the first sentence while generating the rest)
3. Screen-awareness tool with a local vision model (qwen2.5vl)
4. Native Swift shell (per jarvis.md spec) reusing this engine as a local service
