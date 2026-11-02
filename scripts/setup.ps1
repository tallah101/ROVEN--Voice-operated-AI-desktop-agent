# One-command developer setup:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Install Python 3.11 or 3.12 from python.org first." }
py -3.11 -m venv .venv 2>$null; if (-not $?) { py -3.12 -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
# Playwright drives your installed Edge by default; this adds Chromium as a fallback.
.\.venv\Scripts\python -m playwright install chromium
Write-Host "Setup complete. Start ROVEN with:  .\.venv\Scripts\pythonw main.py"
