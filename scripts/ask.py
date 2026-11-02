"""Send a typed command through ROVEN's brain (no microphone, no voice) and print every step.
Use it to check the AI + actions separately from speech.

    .venv\\Scripts\\python scripts\\ask.py "open notepad"

Close the running ROVEN first (tray → Quit) so the two don't act at the same time."""
import logging
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="  %(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
for noisy in ("httpx", "httpx2", "urllib3", "huggingface_hub"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from config import load_settings  # noqa: E402
from security.credentials import get_secret  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    text = " ".join(sys.argv[1:])
    settings = load_settings()
    key = get_secret(f"{settings.llm_provider}_api_key")
    print(f"\n▶ Provider: {settings.llm_provider}   key saved: {'yes' if key else 'NO'}")
    if not key:
        print("  Run: .venv\\Scripts\\python scripts\\configure_ai.py gemini")
        sys.exit(1)
    from core.assistant import Assistant
    assistant = Assistant(settings, queue.Queue(), key)

    def ask_console(summary: str) -> bool:
        print(f"\n  ROVEN asks permission: {summary.splitlines()[0]}")
        return input("  Allow? [y/N] ").strip().lower() in ("y", "yes")
    assistant.permissions.confirm = ask_console

    print(f"▶ You: {text}\n")
    started = time.time()
    reply = assistant.engine.run(text, None, threading.Event(),
                                 on_progress=lambda s, long: print(f"  → action: {s.splitlines()[0]}"))
    print(f"\n▶ ROVEN ({reply.lang}, {time.time() - started:.1f}s): {reply.display}")
    if os.environ.get("ROVEN_SPEAK", "1") == "1":
        print("▶ Speaking the reply…")
        try:
            assistant.tts.speak(reply.speech, reply.lang)
            print("  ✓ voice OK")
        except Exception as exc:
            print(f"  ✗ voice failed: {exc}")


if __name__ == "__main__":
    main()
