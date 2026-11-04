#!/bin/bash
# Build a SELF-CONTAINED Friday.app (Python + dependencies bundled) and a DMG.
# Unlike build_app.sh, the result does not depend on this project folder or venv.
#
#   ./build_standalone.sh
#
# Output: dist/standalone/Friday.app and dist/Friday-standalone.dmg
# Not bundled (downloaded/installed by the user): Ollama + qwen2.5:7b (optional),
# the Whisper model (auto-downloads on first run, ~480 MB).
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

[[ "$(uname)" == "Darwin" ]] || { echo "must run on macOS"; exit 1; }
[[ -x venv/bin/python ]] || { echo "venv missing — run ./setup.sh first"; exit 1; }
venv/bin/python -c "import PyInstaller" 2>/dev/null || venv/bin/pip install -q pyinstaller

echo "▸ Icon"
mkdir -p dist
ICONSET="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s assets/icon_1024.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) assets/icon_1024.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o dist/AppIcon.icns

echo "▸ PyInstaller (a few minutes)"
venv/bin/pyinstaller --noconfirm --clean \
  --distpath dist/standalone --workpath build/pyinstaller friday.spec

APP="dist/standalone/Friday.app"
echo "▸ Ad-hoc codesign"
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP" && echo "  signature ok"

echo "▸ DMG"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
rm -f dist/Friday-standalone.dmg
hdiutil create -volname "Friday" -srcfolder "$STAGE" -ov -format UDZO dist/Friday-standalone.dmg >/dev/null
rm -rf "$STAGE"
hdiutil verify dist/Friday-standalone.dmg | tail -1
ls -lh dist/Friday-standalone.dmg
