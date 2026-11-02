"""Runs PowerShell or Python that ROVEN writes for tasks no dedicated tool covers ('do anything').
Runs as you (never elevated), with a timeout, output captured, and a copy of every script kept."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime

from config import APP_DIR
from security.script_guard import classify

CREATE_NO_WINDOW = 0x08000000
MAX_OUTPUT = 12000


def _keep_copy(language: str, code: str):
    folder = APP_DIR / "scripts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now():%Y%m%d-%H%M%S}.{'ps1' if language == 'powershell' else 'py'}"
    path.write_text(code, encoding="utf-8-sig" if language == "powershell" else "utf-8")
    old = sorted(folder.iterdir())
    for stale in old[:-300]:
        stale.unlink(missing_ok=True)
    return path


def run_script(language: str, code: str, purpose: str, timeout_seconds: int = 120) -> dict:
    classify(language, code)                       # refuses forbidden scripts even if the risk check was skipped
    path = _keep_copy(language, code)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if language == "powershell":
        prefix = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue';\n"
        path.write_text(prefix + code, encoding="utf-8-sig")
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)]
    else:
        # Works in developer mode and inside the installed ROVEN.exe (see main.py --run-script).
        cmd = [sys.executable, str(path)] if not getattr(sys, "frozen", False) else [sys.executable, "--run-script", str(path)]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_seconds, cwd=str(os.path.expanduser("~")),
                              env=env, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Script exceeded {timeout_seconds}s and was stopped.", "script_file": str(path)}
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    return {
        "ok": proc.returncode == 0, "exit_code": proc.returncode, "seconds": round(time.time() - started, 1),
        "output": out[:MAX_OUTPUT], "output_truncated": len(out) > MAX_OUTPUT,
        "errors": err[:4000], "script_file": str(path), "purpose": purpose,
    }
