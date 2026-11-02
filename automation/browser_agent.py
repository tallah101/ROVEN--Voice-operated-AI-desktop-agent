"""Playwright browser agent in a dedicated ROVEN browser profile (Edge by default).
It reads pages, clicks, fills fields, manages tabs and downloads. You sign in to sites yourself once in this
window; ROVEN never types passwords, card numbers or one-time codes."""
from __future__ import annotations

import re
import threading
from pathlib import Path

from config import APP_DIR
from security.action_validator import safe_url, safe_user_path
from security.permission_manager import Risk

RISKY_CLICK = re.compile(r"\b(buy|pay|purchase|order|checkout|check out|place order|submit|send|confirm|delete|remove|"
                         r"transfer|subscribe|book|sign up|register|post|publish|donate|apply|upgrade)\b", re.I)
SENSITIVE_FIELD = re.compile(r"(password|passcode|passwd|card|cvv|cvc|security code|expiry|ssn|social security|iban|"
                             r"account number|routing|\bpin\b|otp|2fa|one[- ]time|verification code|cnic|passport)", re.I)


def click_risk(args: dict) -> Risk:
    return Risk.HIGH if RISKY_CLICK.search(args.get("text", "") or "") else Risk.LOW


def press_risk(args: dict) -> Risk:
    return Risk.MEDIUM if args.get("key", "").lower() in ("enter", "return") else Risk.LOW


def check_fillable(field: str) -> None:
    if SENSITIVE_FIELD.search(field or ""):
        raise PermissionError("ROVEN never types passwords, card numbers, IDs or one-time codes. Please enter that yourself.")


class BrowserAgent:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._pw = None
        self._ctx = None
        self._page = None
        self._thread = None

    def _ensure(self):
        if self._thread not in (None, threading.get_ident()):
            raise RuntimeError("Browser agent must be used from the assistant thread.")
        if self._ctx is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            channel = None if self.settings.browser_channel == "chromium" else self.settings.browser_channel
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(APP_DIR / "browser-profile"), channel=channel, headless=False,
                accept_downloads=True, no_viewport=True, args=["--start-maximized"])
            self._ctx.on("close", lambda _: self._reset())
            self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            self._thread = threading.get_ident()
        if self._page is None or self._page.is_closed():
            pages = [p for p in self._ctx.pages if not p.is_closed()]
            self._page = pages[-1] if pages else self._ctx.new_page()
        return self._page

    def _reset(self):
        self._ctx = self._page = None

    def _state(self, page=None) -> dict:
        page = page or self._page
        return {"url": page.url, "title": page.title()}

    def goto(self, url: str) -> dict:
        page = self._ensure()
        page.goto(safe_url(url), wait_until="domcontentloaded", timeout=45000)
        return self._state()

    def read(self, max_chars: int = 12000) -> dict:
        page = self._ensure()
        text = page.inner_text("body", timeout=15000)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        return {**self._state(), "text": text[:max_chars], "truncated": len(text) > max_chars}

    def links(self, filter: str = "", limit: int = 40) -> dict:
        page = self._ensure()
        links = page.eval_on_selector_all(
            "a[href]", "els => els.filter(e => e.offsetParent !== null).map(e => ({text: e.innerText.trim().slice(0,120), href: e.href}))")
        if filter:
            f = filter.lower()
            links = [l for l in links if f in l["text"].lower() or f in l["href"].lower()]
        links = [l for l in links if l["text"]][:limit]
        return {**self._state(), "links": [{"index": i, **l} for i, l in enumerate(links)]}

    def click(self, text: str, role: str | None = None, nth: int = 0) -> dict:
        page = self._ensure()
        loc = page.get_by_role(role, name=text) if role else page.get_by_text(text, exact=False)
        if loc.count() == 0:
            loc = page.get_by_role("button", name=text)
        if loc.count() == 0:
            loc = page.get_by_role("link", name=text)
        if loc.count() == 0:
            raise LookupError(f"Nothing clickable labelled '{text}' on this page.")
        loc.nth(nth).click(timeout=10000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        newest = [p for p in self._ctx.pages if not p.is_closed()][-1]
        self._page = newest
        return {"clicked": text, **self._state()}

    def fill(self, field: str, value: str) -> dict:
        check_fillable(field)
        page = self._ensure()
        for loc in (page.get_by_label(field), page.get_by_placeholder(field), page.get_by_role("textbox", name=field),
                    page.get_by_role("searchbox", name=field), page.get_by_role("combobox", name=field)):
            if loc.count():
                kind = (loc.first.get_attribute("type") or "").lower()
                if kind == "password":
                    raise PermissionError("That is a password field. Please type it yourself.")
                loc.first.fill(value, timeout=10000)
                return {"filled": field, "verified_value": loc.first.input_value()[:200]}
        raise LookupError(f"No input field labelled '{field}' on this page.")

    def press(self, key: str) -> dict:
        page = self._ensure()
        page.keyboard.press(key.capitalize() if len(key) > 1 else key)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        return {"pressed": key, **self._state()}

    def tabs(self) -> dict:
        self._ensure()
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        return {"tabs": [{"index": i, "title": p.title(), "url": p.url, "active": p == self._page}
                         for i, p in enumerate(pages)]}

    def tab_action(self, action: str, index: int | None = None, url: str | None = None) -> dict:
        self._ensure()
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        if action == "new":
            self._page = self._ctx.new_page()
            if url:
                self._page.goto(safe_url(url), wait_until="domcontentloaded")
        elif action in ("switch", "close"):
            if index is None or not 0 <= index < len(pages):
                raise LookupError("Unknown tab index; call browser_tabs first.")
            if action == "switch":
                self._page = pages[index]
                self._page.bring_to_front()
            else:
                pages[index].close()
                self._page = None
                self._ensure()
        elif action == "back":
            self._page.go_back()
        elif action == "forward":
            self._page.go_forward()
        elif action == "reload":
            self._page.reload()
        return {"action": action, **self._state()}

    def download(self, text: str, folder: str = "~/Downloads") -> dict:
        from automation.documents import unique_path
        page = self._ensure()
        dest_dir = safe_user_path(folder)
        with page.expect_download(timeout=60000) as info:
            page.get_by_text(text, exact=False).first.click()
        dl = info.value
        dest = unique_path(dest_dir / dl.suggested_filename)
        dl.save_as(str(dest))
        return {"downloaded": str(dest), "verified": dest.exists()}

    def upload(self, field: str, path: str) -> dict:
        page = self._ensure()
        p = safe_user_path(path)
        loc = page.get_by_label(field)
        if not loc.count():
            loc = page.locator("input[type=file]")
        loc.first.set_input_files(str(p))
        return {"attached": p.name, "to": field}

    def close(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
            if self._pw:
                self._pw.stop()
        finally:
            self._ctx = self._page = self._pw = None

