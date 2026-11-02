"""Read browsing and search history from Chrome, Edge, Brave and Firefox (your own profiles, read-only copies).
Never touches saved passwords, cookies or payment data."""
from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import APP_DIR

CHROMIUM = {
    "chrome": Path("Google/Chrome/User Data"),
    "edge": Path("Microsoft/Edge/User Data"),
    "brave": Path("BraveSoftware/Brave-Browser/User Data"),
}
WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
SEARCH_PARAMS = {"google.": "q", "bing.com": "q", "duckduckgo.com": "q", "youtube.com": "search_query",
                 "search.yahoo.com": "p", "yandex.": "text"}


def webkit_to_local(us: int) -> datetime:
    return (WEBKIT_EPOCH + timedelta(microseconds=int(us))).astimezone().replace(tzinfo=None)


def local_to_webkit(dt: datetime) -> int:
    return int((dt.astimezone(timezone.utc) - WEBKIT_EPOCH).total_seconds() * 1_000_000)


def search_term_from_url(url: str) -> str | None:
    u = urlparse(url)
    for host, param in SEARCH_PARAMS.items():
        if host in u.netloc and ("search" in u.path or u.path in ("", "/") or "results" in u.path):
            vals = parse_qs(u.query).get(param)
            if vals and vals[0].strip():
                return vals[0].strip()
    return None


def _chromium_profiles(browser: str, base: Path | None = None) -> list[Path]:
    root = (base or Path(os.environ.get("LOCALAPPDATA", ""))) / CHROMIUM[browser]
    if not root.exists():
        return []
    profiles = [root / "Default"] + sorted(p for p in root.glob("Profile *") if p.is_dir())
    return [p for p in profiles if (p / "History").exists()]


def _firefox_profiles(base: Path | None = None) -> list[Path]:
    root = (base or Path(os.environ.get("APPDATA", ""))) / "Mozilla/Firefox/Profiles"
    return [p for p in root.glob("*") if (p / "places.sqlite").exists()] if root.exists() else []


def _snapshot(db: Path) -> Path:
    """Copy the (locked, in-use) database so we read a consistent, read-only snapshot."""
    cache = APP_DIR / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / f"hist-{uuid.uuid4().hex}.sqlite"
    shutil.copy2(db, dest)
    for suffix in ("-wal", "-journal"):
        side = Path(str(db) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(dest) + suffix))
    return dest


def _query(db: Path, sql: str, params: tuple) -> list[tuple]:
    snap = _snapshot(db)
    try:
        conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    finally:
        for suffix in ("", "-wal", "-journal"):
            Path(str(snap) + suffix).unlink(missing_ok=True)


def history(browser: str = "chrome", query: str = "", days: float = 7, limit: int = 100,
            searches_only: bool = False, base: Path | None = None) -> dict:
    since = datetime.now() - timedelta(days=days)
    like = f"%{query}%"
    items: list[dict] = []
    if browser in CHROMIUM:
        profiles = _chromium_profiles(browser, base)
        for prof in profiles:
            if searches_only:
                rows = _query(prof / "History",
                              "SELECT t.term, u.url, u.last_visit_time FROM keyword_search_terms t JOIN urls u ON u.id=t.url_id "
                              "WHERE u.last_visit_time > ? AND t.term LIKE ? ORDER BY u.last_visit_time DESC LIMIT ?",
                              (local_to_webkit(since), like, limit))
                items += [{"time": webkit_to_local(t).strftime("%Y-%m-%d %H:%M"), "search": term, "url": url,
                           "profile": prof.name} for term, url, t in rows]
            else:
                rows = _query(prof / "History",
                              "SELECT u.title, u.url, v.visit_time FROM visits v JOIN urls u ON u.id=v.url "
                              "WHERE v.visit_time > ? AND (u.title LIKE ? OR u.url LIKE ?) ORDER BY v.visit_time DESC LIMIT ?",
                              (local_to_webkit(since), like, like, limit))
                items += [{"time": webkit_to_local(t).strftime("%Y-%m-%d %H:%M"), "title": title or "", "url": url,
                           "profile": prof.name} for title, url, t in rows]
    elif browser == "firefox":
        profiles = _firefox_profiles(base)
        since_us = int(since.timestamp() * 1_000_000)
        for prof in profiles:
            rows = _query(prof / "places.sqlite",
                          "SELECT p.title, p.url, v.visit_date FROM moz_historyvisits v JOIN moz_places p ON p.id=v.place_id "
                          "WHERE v.visit_date > ? AND (p.title LIKE ? OR p.url LIKE ?) ORDER BY v.visit_date DESC LIMIT ?",
                          (since_us, like, like, limit * (3 if searches_only else 1)))
            for title, url, t in rows:
                when = datetime.fromtimestamp(t / 1_000_000).strftime("%Y-%m-%d %H:%M")
                if searches_only:
                    term = search_term_from_url(url)
                    if term:
                        items.append({"time": when, "search": term, "url": url, "profile": prof.name})
                else:
                    items.append({"time": when, "title": title or "", "url": url, "profile": prof.name})
    else:
        raise ValueError("browser must be chrome, edge, brave or firefox")
    if not profiles:
        return {"browser": browser, "count": 0, "items": [], "note": f"No {browser} profile with history was found."}
    items.sort(key=lambda i: i["time"], reverse=True)
    return {"browser": browser, "days": days, "profiles": [p.name for p in profiles], "count": len(items[:limit]),
            "items": items[:limit]}
