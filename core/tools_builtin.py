"""Registers every tool ROVEN may use. Adding a capability = adding a Tool here (allowlist)."""
from __future__ import annotations

from datetime import datetime

from automation import application_control as apps
from automation import browser_control as br
from automation import file_manager as fm
from automation import keyboard_mouse as km
from automation import system_control as sysc
from automation import window_manager as wm
from core.tool_registry import Tool, ToolRegistry
from security.permission_manager import Risk


def S(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


STR = {"type": "string", "minLength": 1}


def build_registry(permissions, audit, memory, catalog: apps.AppCatalog, workflow_store=None) -> ToolRegistry:
    r = ToolRegistry(permissions, audit)
    add = r.register

    # --- general -----------------------------------------------------------------------------
    add(Tool("get_datetime", "Current local date, time and weekday.", S({}),
             lambda: datetime.now().strftime("%A %d %B %Y, %H:%M")))
    add(Tool("remember", "Save a fact or preference the user explicitly asked you to remember. Never credentials.",
             S({"content": STR}, ("content",)), lambda content: {"memory_id": memory.remember(content)},
             summarize=lambda a: f"Remember: {a['content']}"))
    add(Tool("recall", "Search saved memories.", S({"query": {"type": "string"}}),
             lambda query="": memory.search(query)))
    add(Tool("forget", "Delete a saved memory by id.", S({"memory_id": {"type": "integer"}}, ("memory_id",)),
             lambda memory_id: {"deleted": memory.forget(memory_id)}))

    # --- applications & windows --------------------------------------------------------------
    add(Tool("list_installed_apps", "List installed applications whose name contains the filter. Use when unsure of an app's exact name.",
             S({"filter": {"type": "string"}}), lambda filter="": catalog.list_names(filter)))
    add(Tool("open_app", "Open (or bring up) an installed application by name, e.g. 'Slack', 'VS Code', 'Excel'. Verifies a window appears.",
             S({"name": STR}, ("name",)), lambda name: apps.open_app(catalog, name),
             summarize=lambda a: f"Open {a['name']}"))
    add(Tool("close_app", "Politely close an application's windows (it may ask to save).",
             S({"name": STR}, ("name",)), wm.close_app, risk=Risk.MEDIUM,
             summarize=lambda a: f"Close {a['name']}"))
    add(Tool("list_open_windows", "List open windows with their titles and process names.", S({}),
             wm.describe_open_windows))
    add(Tool("focus_window", "Switch to an open window/app by name or title words.",
             S({"query": STR}, ("query",)), wm.focus_window, summarize=lambda a: f"Switch to {a['query']}"))
    add(Tool("window_action", "Minimize, maximize, restore, or snap a window to the left/right half of the screen.",
             S({"query": STR, "action": {"enum": ["minimize", "maximize", "restore", "snap_left", "snap_right"]}},
               ("query", "action")), wm.window_action))

    # --- system ----------------------------------------------------------------------------------
    add(Tool("get_volume", "Current speaker volume and mute state.", S({}), sysc.get_volume))
    add(Tool("set_volume", "Set speaker volume to a percentage.",
             S({"percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ("percent",)), sysc.set_volume))
    add(Tool("change_volume", "Raise (positive) or lower (negative) volume by percentage points.",
             S({"delta": {"type": "integer", "minimum": -100, "maximum": 100}}, ("delta",)), sysc.change_volume))
    add(Tool("set_mute", "Mute or unmute speakers.", S({"muted": {"type": "boolean"}}, ("muted",)), sysc.set_mute))
    add(Tool("set_brightness", "Set built-in display brightness percentage.",
             S({"percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ("percent",)), sysc.set_brightness))
    add(Tool("open_settings_page", "Open a Windows Settings page.",
             S({"page": {"enum": sorted(sysc.SETTINGS_PAGES)}}, ("page",)), sysc.open_settings_page))
    add(Tool("system_status", "CPU, memory, battery and the apps using the most memory.", S({}), sysc.system_status))
    add(Tool("lock_computer", "Lock Windows (user must sign back in).", S({}), sysc.lock_computer))
    add(Tool("power_action", "Shut down, restart, sleep or sign out of Windows.",
             S({"action": {"enum": ["shutdown", "restart", "sleep", "sign_out"]}}, ("action",)),
             sysc.power_action, risk=Risk.HIGH, trustable=False,
             summarize=lambda a: f"{a['action'].replace('_', ' ').title()} the computer"))

    # --- keyboard -------------------------------------------------------------------------------
    add(Tool("type_text", "Type text into the currently focused window (any language). Focus the right window first.",
             S({"text": {"type": "string", "minLength": 1, "maxLength": 5000}}, ("text",)),
             km.type_text, risk=km.typing_risk, trustable=False,
             summarize=lambda a: f"Type into {km.foreground_title() or 'the active window'}: \"{a['text'][:120]}\""))
    add(Tool("press_keys", "Press a key or shortcut, e.g. ['ctrl','c'], ['alt','tab'], ['enter'], ['ctrl','shift','t'].",
             S({"keys": {"type": "array", "items": STR, "minItems": 1, "maxItems": 4}}, ("keys",)),
             km.press_keys, risk=km.keys_risk, trustable=False,
             summarize=lambda a: f"Press {'+'.join(a['keys'])} in {km.foreground_title() or 'the active window'}"))
    add(Tool("scroll", "Scroll the window under the mouse.",
             S({"direction": {"enum": ["up", "down"]}, "amount": {"type": "integer", "minimum": 1, "maximum": 50}},
               ("direction",)), km.scroll))

    # --- browser ----------------------------------------------------------------------------------
    add(Tool("open_url", "Open a web address in the default browser.", S({"url": STR}, ("url",)), br.open_url))
    add(Tool("open_web_search", "Open a Google, YouTube or Bing search in the user's default browser for them to look at.",
             S({"query": STR, "site": {"enum": sorted(br.SEARCH_URLS)}}, ("query",)), br.web_search))

    # --- files ------------------------------------------------------------------------------------
    add(Tool("find_files", "Search the user's Desktop/Documents/Downloads/Pictures/Videos/Music (or a given folder) by name, extension and recency.",
             S({"query": {"type": "string"}, "extensions": {"type": "array", "items": STR},
                "modified_within_days": {"type": "number", "minimum": 0}, "folder": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50}}), fm.find_files))
    add(Tool("open_path", "Open a file or folder (e.g. '~/Downloads') with its default app.",
             S({"path": STR}, ("path",)), fm.open_path))
    add(Tool("read_document", "Read text from txt, md, csv, pdf, docx, xlsx or pptx files.",
             S({"path": STR, "max_chars": {"type": "integer", "minimum": 500, "maximum": 40000}}, ("path",)),
             fm.read_document, untrusted_output=True))
    add(Tool("create_folder", "Create a new folder inside the user's home folder.",
             S({"path": STR}, ("path",)), fm.create_folder, risk=Risk.MEDIUM,
             summarize=lambda a: f"Create folder {a['path']}"))
    add(Tool("move_path", "Move a file or folder into another folder (never overwrites).",
             S({"path": STR, "destination_folder": STR}, ("path", "destination_folder")), fm.move_path,
             risk=Risk.MEDIUM, summarize=lambda a: f"Move {a['path']} to {a['destination_folder']}"))
    add(Tool("rename_path", "Rename a file or folder (never overwrites).",
             S({"path": STR, "new_name": STR}, ("path", "new_name")), fm.rename_path,
             risk=Risk.MEDIUM, summarize=lambda a: f"Rename {a['path']} to {a['new_name']}"))
    add(Tool("move_to_recycle_bin", "Send a file or folder to the Recycle Bin.",
             S({"path": STR}, ("path",)), fm.move_to_recycle_bin, risk=Risk.HIGH, trustable=False,
             summarize=lambda a: f"Send {a['path']} to the Recycle Bin"))
    if workflow_store is not None:
        def interrupted():
            wf = workflow_store.latest_interrupted()
            if not wf:
                return {"interrupted_task": None}
            workflow_store.acknowledge(wf["id"])
            return {"request": wf["request"], "started": wf["started"], "status": wf["status"],
                    "completed_steps": [s for s in wf["steps"] if s["ok"]],
                    "note": "Do not repeat completed steps that had side effects (sent, created, moved...)."}
        add(Tool("get_interrupted_task", "Details of the last task that was interrupted (crash, power loss or emergency "
                 "stop), with the steps already completed, so it can be resumed safely.", S({}), interrupted))
    return r
