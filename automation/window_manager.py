"""Enumerate, focus, resize and close top-level windows (pywin32)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from core.text_match import match_score


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process: str
    pid: int


def list_windows() -> list[WindowInfo]:
    import psutil
    import win32con
    import win32gui
    import win32process

    own_pid = os.getpid()
    found: list[WindowInfo] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == own_pid:
            return True
        try:
            name = psutil.Process(pid).name()
        except Exception:
            name = ""
        found.append(WindowInfo(hwnd, title, name, pid))
        return True

    win32gui.EnumWindows(callback, None)
    return found


def match_windows(query: str, windows: list[WindowInfo] | None = None, min_score: float = 0.6) -> list[WindowInfo]:
    windows = list_windows() if windows is None else windows
    scored = []
    for w in windows:
        parts = [w.title, w.process, *w.title.split(" - ")]
        score = max(match_score(query, p) for p in parts if p)
        if score >= min_score:
            scored.append((score, w))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [w for _, w in scored]


def foreground() -> WindowInfo | None:
    import win32gui
    hwnd = win32gui.GetForegroundWindow()
    return next((w for w in list_windows() if w.hwnd == hwnd), None)


def _best(query: str) -> WindowInfo:
    matches = match_windows(query)
    if not matches:
        raise LookupError(f"No open window matches '{query}'.")
    return matches[0]


def describe_open_windows() -> list[dict]:
    return [{"title": w.title, "process": w.process} for w in list_windows()]


def focus_window(query: str) -> dict:
    import win32api
    import win32con
    import win32gui
    w = _best(query)
    if win32gui.IsIconic(w.hwnd):
        win32gui.ShowWindow(w.hwnd, win32con.SW_RESTORE)
    # Windows only lets the foreground process steal focus; a synthetic Alt press is the documented workaround.
    win32api.keybd_event(0x12, 0, 0, 0)
    try:
        win32gui.SetForegroundWindow(w.hwnd)
    finally:
        win32api.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.25)
    return {"window": w.title, "verified": win32gui.GetForegroundWindow() == w.hwnd}


def window_action(query: str, action: str) -> dict:
    import win32api
    import win32con
    import win32gui
    w = _best(query)
    h = w.hwnd
    if action == "minimize":
        win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
        time.sleep(0.2)
        ok = bool(win32gui.IsIconic(h))
    elif action == "maximize":
        win32gui.ShowWindow(h, win32con.SW_MAXIMIZE)
        time.sleep(0.2)
        ok = win32gui.GetWindowPlacement(h)[1] == win32con.SW_SHOWMAXIMIZED
    elif action == "restore":
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
        time.sleep(0.2)
        ok = not win32gui.IsIconic(h)
    elif action in ("snap_left", "snap_right"):
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
        monitor = win32api.MonitorFromWindow(h, 2)
        left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]
        half = (right - left) // 2
        x = left if action == "snap_left" else left + half
        win32gui.MoveWindow(h, x, top, half, bottom - top, True)
        ok = True
    else:
        raise ValueError(f"Unknown window action {action}")
    return {"window": w.title, "action": action, "verified": ok}


def close_app(query: str, wait: float = 3.0) -> dict:
    """Politely close (WM_CLOSE) the windows of the best-matching app; never force-kills."""
    import win32con
    import win32gui
    best = _best(query)
    targets = [w for w in list_windows() if w.process and w.process == best.process] or [best]
    for w in targets:
        win32gui.PostMessage(w.hwnd, win32con.WM_CLOSE, 0, 0)
    deadline = time.time() + wait
    while time.time() < deadline and any(win32gui.IsWindow(w.hwnd) for w in targets):
        time.sleep(0.25)
    remaining = [w.title for w in targets if win32gui.IsWindow(w.hwnd)]
    return {"app": best.process or best.title, "closed_windows": len(targets) - len(remaining),
            "still_open": remaining,
            "note": "Windows still open may be asking to save changes." if remaining else ""}
