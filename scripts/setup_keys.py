"""Store or remove secrets in Windows Credential Manager.

    python scripts/setup_keys.py gemini          # Google Gemini API key
    python scripts/setup_keys.py anthropic       # Anthropic API key
    python scripts/setup_keys.py porcupine       # Picovoice access key (only for the porcupine engine)
    python scripts/setup_keys.py anthropic --delete
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from security.credentials import delete_secret, set_secret  # noqa: E402

NAMES = {"gemini": "gemini_api_key", "anthropic": "anthropic_api_key", "porcupine": "porcupine_access_key"}

if len(sys.argv) < 2 or sys.argv[1] not in NAMES:
    print(__doc__)
    sys.exit(1)
name = NAMES[sys.argv[1]]
if "--delete" in sys.argv:
    delete_secret(name)
    print("Deleted.")
else:
    set_secret(name, getpass.getpass(f"Paste {sys.argv[1]} key (hidden): ").strip())
    print("Saved to Windows Credential Manager.")
