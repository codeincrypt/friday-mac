#!/bin/bash
# Build Friday.app — a real macOS app bundle that launches this project's
# venv. Run setup.sh first (it calls this for you).
#
#   ./build_app.sh            build + install to /Applications (or ~/Applications)
#   ./build_app.sh --login    also start Friday automatically at login
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")" && pwd)"
APP="$PROJECT/dist/Friday.app"
PY="$PROJECT/venv/bin/python"

[[ "$(uname)" == "Darwin" ]] || { echo "build_app.sh must run on macOS"; exit 1; }
[[ -x "$PY" ]] || { echo "venv missing — run ./setup.sh first"; exit 1; }

echo "▸ Building $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ---- launcher (exec keeps the PID, so macOS attributes mic access to Friday.app)
cat > "$APP/Contents/MacOS/Friday" <<EOF
#!/bin/bash
LOG="\$HOME/Library/Application Support/Friday/launch.log"
mkdir -p "\$(dirname "\$LOG")"
cd "$PROJECT"
export PYTHONUNBUFFERED=1
exec "$PY" "$PROJECT/app.py" >>"\$LOG" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/Friday"

# ---- icon
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
SRC="$PROJECT/assets/icon_1024.png"
for s in 16 32 128 256 512; do
  sips -z $s $s "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

# ---- Info.plist
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Friday</string>
  <key>CFBundleDisplayName</key><string>Friday</string>
  <key>CFBundleIdentifier</key><string>local.friday.assistant</string>
  <key>CFBundleVersion</key><string>2.0.0</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>CFBundleExecutable</key><string>Friday</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Friday listens for your voice commands in English and Hindi. Audio is transcribed locally on this Mac.</string>
  <key>NSAppleEventsUsageDescription</key>
  <string>Friday controls apps such as Chrome, Mail, Music and Finder when you ask it to.</string>
  <key>NSSpeechRecognitionUsageDescription</key>
  <string>Friday transcribes your voice commands locally.</string>
</dict>
</plist>
EOF

# ---- ad-hoc signature so macOS remembers the permissions you grant
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || echo "  (codesign skipped)"

# ---- install
DEST="/Applications"
[[ -w "$DEST" ]] || DEST="$HOME/Applications"
mkdir -p "$DEST"
rm -rf "$DEST/Friday.app"
cp -R "$APP" "$DEST/"
echo "✓ Installed $DEST/Friday.app"

if [[ "${1:-}" == "--login" ]]; then
  osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$DEST/Friday.app\", hidden:false}" >/dev/null \
    && echo "✓ Friday will start at login"
fi
echo "  Open it from Launchpad / Spotlight (⌘Space → Friday)."
