"""Phase 1 browser control: open URLs and searches in the default browser.
Playwright-driven page reading, form filling and tab control are Phase 2b (not implemented)."""
from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus

from security.action_validator import safe_url

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "bing": "https://www.bing.com/search?q={}",
}


def open_url(url: str) -> dict:
    url = safe_url(url)
    webbrowser.open(url, new=2)
    return {"opened": url, "verified": False, "note": "Opened in the default browser; page content is not read yet."}


def web_search(query: str, site: str = "google") -> dict:
    url = SEARCH_URLS[site].format(quote_plus(query))
    webbrowser.open(url, new=2)
    return {"opened": url}
