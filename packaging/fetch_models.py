"""Puts the speech models inside the build so ROVEN works right after installation (no first-run download).
Usage: python packaging/fetch_models.py dist/ROVEN/models [small tiny]"""
import sys
from pathlib import Path

from faster_whisper import download_model

target = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/ROVEN/models")
sizes = sys.argv[2:] or ["small", "tiny"]          # small = recognition, tiny = wake-word fallback
for size in sizes:
    dest = target / f"faster-whisper-{size}"
    download_model(size, output_dir=str(dest))
    print("bundled", size, "->", dest)
try:
    import openwakeword
    openwakeword.utils.download_models()             # feature models live inside the package folder
except Exception as exc:
    print("openWakeWord feature models will download on first use:", exc)
