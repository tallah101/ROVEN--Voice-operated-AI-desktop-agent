"""Choose ROVEN's AI, save the key securely and test it live.

    python scripts\\configure_ai.py gemini       # Google Gemini (free tier)
    python scripts\\configure_ai.py anthropic    # Anthropic Claude
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_settings, save_settings  # noqa: E402
from security.credentials import get_secret, set_secret  # noqa: E402


def test_gemini(key: str, settings) -> str:
    from core.llm_gemini import GeminiClient
    client = GeminiClient(key, settings)
    print("  Checking which Gemini models your key can use…")
    settings.gemini_order = []
    cands = client.candidates()
    print("  Available Flash models:", ", ".join(cands))
    print("  Speed test (each model answers a tiny question):")
    timed = client.speed_test(cands[:5])
    if not timed:
        raise RuntimeError("No Gemini model answered. Google may be overloaded; try again in a few minutes.")
    settings.gemini_order = [m for m, _ in timed]
    client._candidates = settings.gemini_order + [m for m in cands if m not in settings.gemini_order]
    print(f"  Fastest: {timed[0][0]} ({timed[0][1]:.1f}s) — ROVEN will use it first, others as backup.")
    reply = client.messages.create(model="", max_tokens=600, system=[{"type": "text", "text": "Reply with exactly: ROVEN OK"}],
                                   tools=[], messages=[{"role": "user", "content": [{"type": "text", "text": "Test"}]}])
    text = "".join(b.get("text", "") for b in reply.content).strip()
    if "stopped without an answer" in text:
        raise RuntimeError(text)
    return f"{client.active_model} replied: {text[:60]}"


def test_anthropic(key: str, settings) -> str:
    import anthropic
    r = anthropic.Anthropic(api_key=key).messages.create(model=settings.llm_model, max_tokens=20,
                                                          messages=[{"role": "user", "content": "Reply with exactly: ROVEN OK"}])
    return f"{settings.llm_model} replied: {r.content[0].text.strip()[:60]}"


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("gemini", "anthropic"):
        print(__doc__)
        sys.exit(1)
    provider = sys.argv[1]
    secret = f"{provider}_api_key"
    settings = load_settings()
    existing = get_secret(secret)
    prompt = f"Paste your {provider.title()} API key (input is hidden)"
    key = getpass.getpass(prompt + (" — or press Enter to keep the saved one: " if existing else ": ")).strip() or existing
    if not key:
        print("No key entered.")
        sys.exit(1)
    settings.llm_provider = provider
    try:
        result = test_gemini(key, settings) if provider == "gemini" else test_anthropic(key, settings)
    except Exception as exc:
        print(f"\n  ✗ The key did not work: {exc}")
        print("  Nothing was saved. Check the key and try again.")
        sys.exit(1)
    set_secret(secret, key)
    save_settings(settings)
    print(f"\n  ✓ Works — {result}")
    print(f"  ✓ Key saved to Windows Credential Manager; ROVEN will use {provider.title()}.")


if __name__ == "__main__":
    main()
