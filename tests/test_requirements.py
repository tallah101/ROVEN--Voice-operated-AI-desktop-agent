"""Guards against dependencies silently disappearing from requirements.txt (this happened once)."""
from pathlib import Path

REQUIRED = ["customtkinter", "anthropic", "faster-whisper", "openwakeword", "edge-tts", "pywin32", "pyautogui",
            "keyring", "jsonschema", "requests", "google-auth", "google-auth-oauthlib", "uiautomation", "playwright",
            "mss", "python-docx", "openpyxl", "python-pptx", "pypdf", "psutil", "pycaw", "pystray", "send2trash"]


def test_every_runtime_dependency_is_listed():
    text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text().lower()
    names = {line.split(">=")[0].split("==")[0].strip() for line in text.splitlines() if line and not line.startswith("#")}
    missing = [r for r in REQUIRED if r not in names]
    assert not missing, missing
