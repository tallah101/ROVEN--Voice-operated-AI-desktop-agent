"""Clipboard, processes and other everyday system helpers."""
from __future__ import annotations

PROTECTED = {"system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
             "svchost.exe", "explorer.exe", "dwm.exe", "fontdrvhost.exe", "registry", "memory compression",
             "msmpeng.exe", "securityhealthservice.exe", "audiodg.exe", "spoolsv.exe"}


def clipboard_get() -> dict:
    import pyperclip
    text = pyperclip.paste() or ""
    return {"text": text[:10000], "truncated": len(text) > 10000}


def clipboard_set(text: str) -> dict:
    import pyperclip
    pyperclip.copy(text)
    return {"copied_characters": len(text)}


def list_processes(filter: str = "", sort_by: str = "memory", limit: int = 30) -> dict:
    import psutil
    rows = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent", "username"]):
        try:
            name = p.info["name"] or ""
            if filter and filter.lower() not in name.lower():
                continue
            rows.append({"pid": p.info["pid"], "name": name, "memory_mb": round(p.info["memory_info"].rss / 1e6),
                         "cpu_percent": p.info["cpu_percent"]})
        except Exception:
            continue
    key = "memory_mb" if sort_by == "memory" else "cpu_percent" if sort_by == "cpu" else "name"
    rows.sort(key=lambda r: r[key] or 0, reverse=key != "name")
    return {"count": len(rows), "processes": rows[:limit]}


def end_process(name_or_pid: str) -> dict:
    import psutil
    targets = []
    for p in psutil.process_iter(["pid", "name"]):
        if str(p.info["pid"]) == name_or_pid or (p.info["name"] or "").lower() in (name_or_pid.lower(), name_or_pid.lower() + ".exe"):
            targets.append(p)
    if not targets:
        raise LookupError(f"No running process matches '{name_or_pid}'.")
    if any((t.info["name"] or "").lower() in PROTECTED for t in targets):
        raise PermissionError("That is a core Windows process; ending it could crash or lock the PC.")
    for t in targets:
        t.terminate()
    gone, alive = psutil.wait_procs(targets, timeout=5)
    return {"ended": len(gone), "still_running": [p.pid for p in alive]}
