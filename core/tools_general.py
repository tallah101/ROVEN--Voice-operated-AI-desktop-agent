"""General PC-control tools: screen vision, scripts ('do anything'), browser history, clipboard, processes,
reminders, and a results window to *show* things to the user."""
from __future__ import annotations

from automation import browser_history as bh
from automation import screen
from automation import system_extras as sx
from automation.scripting import run_script
from automation.ui_automation import RISKY_CONTROL
from core.tool_registry import Tool
from security.permission_manager import Risk
from security.script_guard import ForbiddenScript, classify


def S(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


STR = {"type": "string", "minLength": 1}
NUM = {"type": "number", "minimum": 0}


def register_general_tools(r, settings, show, reminders) -> None:
    add = r.register

    # ---- screen vision -----------------------------------------------------------------------------
    add(Tool("look_at_screen", "Take a screenshot so you can SEE the screen. Use when list_controls can't find what you "
             "need, to check what happened after an action, or when the user says 'what's on my screen'.",
             S({"monitor": {"type": "integer", "minimum": 1, "maximum": 6}}),
             lambda monitor=1: screen.capture(monitor, settings.screenshot_max_width)))
    pointer_risk = lambda a: Risk.HIGH if RISKY_CONTROL.search(a.get("target", "")) else Risk.LOW  # noqa: E731
    add(Tool("click_at", "Click at a point in the latest screenshot (image pixel coordinates). 'target' must say what "
             "you are clicking, e.g. 'Search box' or 'Send button'.",
             S({"x": NUM, "y": NUM, "target": STR, "button": {"enum": ["left", "right", "middle"]},
                "clicks": {"type": "integer", "minimum": 1, "maximum": 3}}, ("x", "y", "target")),
             screen.click_at, risk=pointer_risk, trustable=False,
             summarize=lambda a: f"Click '{a['target']}' on screen"))
    add(Tool("move_mouse_to", "Move the mouse to a point in the latest screenshot (e.g. to hover a menu).",
             S({"x": NUM, "y": NUM}, ("x", "y")), screen.move_to))
    add(Tool("drag_at", "Drag from one point to another in the latest screenshot.",
             S({"x1": NUM, "y1": NUM, "x2": NUM, "y2": NUM, "target": STR}, ("x1", "y1", "x2", "y2", "target")),
             screen.drag, risk=Risk.MEDIUM, summarize=lambda a: f"Drag {a['target']}"))
    add(Tool("save_screenshot", "Save a screenshot of all screens as a PNG (default Pictures\\Screenshots).",
             S({"folder": {"type": "string"}}), lambda folder=None: screen.save_screenshot(folder)))

    # ---- scripts: anything not covered by a dedicated tool -------------------------------------------
    def script_risk(a):
        risk = classify(a["language"], a["code"])          # forbidden scripts never reach here (precheck)
        return Risk.HIGH if r.tainted else risk

    def script_summary(a):
        try:
            level = "changes things" if classify(a["language"], a["code"]) == Risk.HIGH else "read-only"
        except ForbiddenScript as exc:
            return str(exc)
        first_lines = "\n".join(a["code"].strip().splitlines()[:6])
        return f"Run a {a['language']} script to {a['purpose']} ({level}).\n{first_lines}"

    def guarded_run(language, code, purpose, timeout_seconds=None):
        return run_script(language, code, purpose, timeout_seconds or settings.script_timeout_seconds)

    add(Tool("run_script", "Run a PowerShell (preferred on Windows) or Python script for anything no other tool covers: "
             "system information, installed software, network/Wi-Fi details, disk usage, bulk file operations, "
             "settings queries, scheduled tasks, Office automation, data processing. Print results to stdout. "
             "Prefer read-only scripts; anything that changes the PC is confirmed with the user. Runs without admin "
             "rights. Scripts that touch saved passwords, elevate, weaken security or wipe data are refused.",
             S({"language": {"enum": ["powershell", "python"]}, "code": {"type": "string", "minLength": 1, "maxLength": 20000},
                "purpose": {"type": "string", "minLength": 3, "description": "Plain-language purpose, spoken to the user"},
                "timeout_seconds": {"type": "integer", "minimum": 5, "maximum": 600}}, ("language", "code", "purpose")),
             guarded_run, risk=script_risk, trust_listed=True, summarize=script_summary, long_running=True,
             precheck=lambda a: classify(a["language"], a["code"])))

    # ---- browser history -------------------------------------------------------------------------
    add(Tool("browser_history", "The user's own browsing history (or search terms with searches_only) from Chrome, Edge, "
             "Brave or Firefox, newest first. Follow with show_results to display it.",
             S({"browser": {"enum": ["chrome", "edge", "brave", "firefox"]}, "query": {"type": "string"},
                "days": {"type": "number", "minimum": 0.05, "maximum": 365},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000}, "searches_only": {"type": "boolean"}}),
             bh.history, untrusted_output=True))

    # ---- show things on screen -------------------------------------------------------------------
    def show_results(title, columns=None, rows=None, text=None):
        if not rows and not text:
            raise ValueError("Give rows (with columns) or text to show.")
        show({"title": title, "columns": columns or [], "rows": rows or [], "text": text or ""})
        return {"shown": True, "rows": len(rows or [])}

    add(Tool("show_results", "Open a ROVEN window that SHOWS results to the user: a table (columns + rows) or text. "
             "Use whenever the user says 'show me' a list, history, files, results or a long answer. Links in tables "
             "open on double-click.",
             S({"title": STR, "columns": {"type": "array", "items": STR, "maxItems": 12},
                "rows": {"type": "array", "items": {"type": "array"}, "maxItems": 5000},
                "text": {"type": "string", "maxLength": 200000}}, ("title",)), show_results))

    # ---- clipboard & processes -------------------------------------------------------------------
    add(Tool("clipboard_get", "Read the clipboard text.", S({}), sx.clipboard_get, untrusted_output=True))
    add(Tool("clipboard_set", "Copy text to the clipboard.", S({"text": {"type": "string", "maxLength": 100000}}, ("text",)),
             sx.clipboard_set))
    add(Tool("list_processes", "Running processes sorted by memory, cpu or name.",
             S({"filter": {"type": "string"}, "sort_by": {"enum": ["memory", "cpu", "name"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200}}), sx.list_processes))
    add(Tool("end_process", "Force-close a frozen program by name or PID (core Windows processes are refused).",
             S({"name_or_pid": STR}, ("name_or_pid",)), sx.end_process, risk=Risk.HIGH, trustable=False,
             summarize=lambda a: f"Force-close {a['name_or_pid']} (unsaved work in it will be lost)"))

    # ---- reminders -----------------------------------------------------------------------------------
    add(Tool("set_reminder", "Speak a reminder at a local time 'YYYY-MM-DD HH:MM'.",
             S({"when": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$"}, "message": STR},
               ("when", "message")), reminders.add))
    add(Tool("list_reminders", "Pending reminders.", S({}), reminders.pending))
    add(Tool("cancel_reminder", "Cancel a reminder by id.", S({"reminder_id": {"type": "integer"}}, ("reminder_id",)),
             lambda reminder_id: reminders.cancel(reminder_id)))
