"""Discover installed apps dynamically (Start Menu shortcuts + Get-StartApps) and launch them."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from core.text_match import normalize, rank

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class AppEntry:
    name: str
    kind: str      # lnk | uwp | exe | uri
    target: str


BUILTIN_APPS = [
    AppEntry("Notepad", "exe", "notepad.exe"),
    AppEntry("Calculator", "uri", "calculator:"),
    AppEntry("Task Manager", "exe", "taskmgr.exe"),
    AppEntry("File Explorer", "exe", "explorer.exe"),
    AppEntry("Settings", "uri", "ms-settings:"),
    AppEntry("Control Panel", "exe", "control.exe"),
    AppEntry("Paint", "exe", "mspaint.exe"),
]
ALIASES = {
    "vs code": "Visual Studio Code", "vscode": "Visual Studio Code",
    "chrome": "Google Chrome", "edge": "Microsoft Edge", "explorer": "File Explorer",
    "files": "File Explorer", "my computer": "File Explorer", "calc": "Calculator",
    "taskmanager": "Task Manager", "firefox": "Firefox",
}
_SKIP = ("uninstall", "readme", "release notes", "documentation", "help", "website", "license", "manual")


class AppCatalog:
    def __init__(self) -> None:
        self._apps: list[AppEntry] | None = None
        self._lock = threading.Lock()

    def refresh(self) -> int:
        found: dict[str, AppEntry] = {}
        for e in self._start_apps():
            found.setdefault(normalize(e.name), e)
        for e in self._start_menu_shortcuts():
            found[normalize(e.name)] = e
        for e in BUILTIN_APPS:
            found[normalize(e.name)] = e
        apps = sorted(found.values(), key=lambda e: e.name.lower())
        with self._lock:
            self._apps = apps
        log.info("Discovered %d applications", len(apps))
        return len(apps)

    def apps(self) -> list[AppEntry]:
        if self._apps is None:
            self.refresh()
        return self._apps or []

    @staticmethod
    def _start_menu_shortcuts():
        roots = [
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for root in roots:
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if p.suffix.lower() in (".lnk", ".url") and not any(s in p.stem.lower() for s in _SKIP):
                    yield AppEntry(p.stem, "lnk", str(p))

    @staticmethod
    def _start_apps() -> list[AppEntry]:
        """Get-StartApps covers Store/UWP apps (WhatsApp, Spotify, Settings pages...). Fixed command, no AI input."""
        if os.name != "nt":
            return []
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=25, creationflags=CREATE_NO_WINDOW,
            ).stdout
            data = json.loads(out) if out.strip() else []
            if isinstance(data, dict):
                data = [data]
            return [AppEntry(d["Name"], "uwp", d["AppID"]) for d in data
                    if d.get("Name") and d.get("AppID") and not any(s in d["Name"].lower() for s in _SKIP)]
        except Exception:
            log.exception("Get-StartApps failed")
            return []

    def find(self, query: str) -> AppEntry | None:
        apps = self.apps()
        names = [a.name for a in apps]
        queries = [query]
        alias = ALIASES.get(normalize(query))
        if alias:
            queries.insert(0, alias)
        best = None
        for q in queries:
            r = rank(q, names, min_score=0.6, limit=1)
            if r and (best is None or r[0][1] > best[1]):
                best = r[0]
        return apps[best[0]] if best else None

    def suggestions(self, query: str, n: int = 5) -> list[str]:
        names = [a.name for a in self.apps()]
        return [names[i] for i, _ in rank(query, names, min_score=0.35, limit=n)]

    def list_names(self, filter: str = "") -> list[str]:
        f = normalize(filter)
        return [a.name for a in self.apps() if not f or f in normalize(a.name)][:80]

    @staticmethod
    def launch(entry: AppEntry) -> None:
        if entry.kind in ("lnk", "uri"):
            os.startfile(entry.target)  # type: ignore[attr-defined]
        elif entry.kind == "uwp":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{entry.target}"])
        else:
            subprocess.Popen([entry.target])


def open_app(catalog: AppCatalog, name: str, wait_seconds: float = 10.0) -> dict:
    from automation import window_manager as wm
    entry = catalog.find(name)
    if entry is None:
        return {"ok": False, "error": f"No installed app matches '{name}'.", "similar": catalog.suggestions(name)}
    before = {w.hwnd for w in wm.list_windows()}
    catalog.launch(entry)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(0.5)
        windows = wm.list_windows()
        matching = wm.match_windows(entry.name, windows) or wm.match_windows(name, windows)
        new_match = next((w for w in matching if w.hwnd not in before), None)
        hit = new_match or (matching[0] if matching else None)
        if hit:
            return {"ok": True, "app": entry.name, "verified": True, "window": hit.title}
    return {"ok": True, "app": entry.name, "verified": False,
            "note": "Launch command sent, but no matching window appeared within the wait time."}
