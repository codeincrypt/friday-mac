#!/bin/bash
# One-shot installer for Friday on macOS (Apple Silicon recommended).
#   chmod +x setup.sh build_app.sh && ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

say_step() { printf "\n\033[36m▸ %s\033[0m\n" "$1"; }
[[ "$(uname)" == "Darwin" ]] || { echo "Friday runs on macOS only."; exit 1; }

# ---------- Python ----------
say_step "Checking Python (3.10+)"
PY=""
for c in python3.12 python3.11 python3.13 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [[ -z "$PY" ]]; then
  if command -v brew >/dev/null; then brew install python@3.12; PY="$(brew --prefix)/bin/python3.12"
  else echo "Install Python 3.10+ (https://www.python.org/downloads/ or Homebrew) and re-run."; exit 1; fi
fi
echo "  using $PY ($("$PY" --version))"

say_step "Creating virtual environment"
[[ -d venv ]] || "$PY" -m venv venv
./venv/bin/python -m pip install --upgrade pip wheel >/dev/null
./venv/bin/pip install -r requirements.txt

[[ -f .env ]] || { cp .env.example .env; echo "  created .env (edit it any time)"; }
MODEL="$(grep -E '^JARVIS_LOCAL_MODEL=' .env | cut -d= -f2 || true)"; MODEL="${MODEL:-qwen2.5:7b}"
WHISPER="$(grep -E '^WHISPER_MODEL=' .env | cut -d= -f2 || true)"; WHISPER="${WHISPER:-small}"

# ---------- Ollama (offline brain) ----------
say_step "Setting up the offline brain (Ollama + $MODEL)"
if ! command -v ollama >/dev/null; then
  if command -v brew >/dev/null; then brew install ollama
  else echo "  Install Ollama from https://ollama.com/download, then re-run this script."; fi
fi
if command -v ollama >/dev/null; then
  if ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
    (open -a Ollama 2>/dev/null || (nohup ollama serve >/dev/null 2>&1 &)) ; sleep 4
  fi
  ollama pull "$MODEL"
  if command -v brew >/dev/null && brew list ollama >/dev/null 2>&1; then
    brew services start ollama >/dev/null 2>&1 || true   # keep Ollama running after reboots
  fi
fi

# ---------- Whisper + voices (downloaded once, then offline) ----------
say_step "Downloading Whisper '$WHISPER' speech model (one time)"
./venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('$WHISPER', device='cpu', compute_type='int8'); print('  ok')"

say_step "Caching Friday's neural voice lines (English + Hindi)"
./venv/bin/python - <<'EOF'
from jarvis import phrases, speak
speak._speaker.precache(list(phrases.all_static_lines()))
print("  ok" if speak._speaker._edge_ok else "  edge-tts unavailable — macOS voices will be used")
EOF

# ---------- App bundle ----------
say_step "Building Friday.app"
chmod +x build_app.sh
./build_app.sh "$@"

cat <<'EOF'

✅ Friday is installed.

First launch — macOS will ask for permissions. Allow them for "Friday":
  • Microphone                       (to hear you)
  • Accessibility                     (typing and key presses; Option+J needs no permission)
    System Settings → Privacy & Security → add Friday.app
  • Automation pop-ups for Chrome / Mail / Music → click OK

Try:  "Friday, open Chrome"   ·   "फ्राइडे, यूट्यूब पर अरिजीत सिंह के गाने चलाओ"
      "Friday, volume kam karo" ·  "फ्राइडे, बैटरी कितनी है?"
EOF
