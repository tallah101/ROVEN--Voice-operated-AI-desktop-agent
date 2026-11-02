# PyInstaller spec. Build with:  pyinstaller packaging\ROVEN.spec --noconfirm --distpath dist --workpath build
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "roven.ico")

datas, binaries, hidden = [], [], []
for pkg in ("customtkinter", "faster_whisper", "ctranslate2", "openwakeword", "onnxruntime", "tokenizers",
            "edge_tts", "uiautomation", "playwright", "google_auth_oauthlib", "certifi", "mss", "miniaudio"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception as exc:
        print("collect_all skipped", pkg, exc)
datas += collect_data_files("pystray")
hidden += ["pycaw.pycaw", "comtypes.stream", "win32timezone", "keyring.backends.Windows", "win32ctypes.core",
           "pyttsx3.drivers", "pyttsx3.drivers.sapi5", "docx", "openpyxl", "pptx", "pypdf", "send2trash",
           "screen_brightness_control", "google.auth.transport.requests", "google.oauth2.credentials"]

a = Analysis([os.path.join(ROOT, "main.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=["matplotlib", "IPython", "pytest", "tkinter.test"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ROVEN", console=False,
          icon=ICON if os.path.exists(ICON) else None, uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ROVEN")
