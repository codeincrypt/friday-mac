# PyInstaller spec for the standalone Friday.app (see build_standalone.sh).
# Bundles Python + all dependencies; models (Whisper, Ollama) are NOT bundled.
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

datas = [("jarvis/ui", "jarvis/ui"), ("assets", "assets")]
binaries = []
hiddenimports = [
    "webview.platforms.cocoa", "objc", "AppKit", "Foundation", "WebKit", "Quartz",
    "PyObjCTools", "UniformTypeIdentifiers", "Security",
]

for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "sounddevice",
            "_sounddevice_data", "edge_tts", "tokenizers", "webview"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # keep building; the smoke test will reveal real gaps
        print(f"[friday.spec] collect_all({pkg}) skipped: {e}")

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Friday",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Friday")
app = BUNDLE(
    coll,
    name="Friday.app",
    icon="dist/AppIcon.icns",
    bundle_identifier="local.friday.assistant",
    info_plist={
        "CFBundleName": "Friday",
        "CFBundleDisplayName": "Friday",
        "CFBundleVersion": "2.0.0",
        "CFBundleShortVersionString": "2.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSMicrophoneUsageDescription": "Friday listens for your voice commands in English and Hindi. Audio is transcribed locally on this Mac.",
        "NSAppleEventsUsageDescription": "Friday controls apps such as Chrome, Mail, Music and Finder when you ask it to.",
        "NSSpeechRecognitionUsageDescription": "Friday transcribes your voice commands locally.",
    },
)
