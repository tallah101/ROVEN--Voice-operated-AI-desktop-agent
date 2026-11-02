"""Windows UI Automation: lets ROVEN see and operate controls inside any app through the accessibility
tree (buttons, menus, text fields, list items) — no screenshots or webcam needed."""
from __future__ import annotations

import re
import threading

from core.text_match import match_score
from security.permission_manager import Risk

RISKY_CONTROL = re.compile(r"\b(send|submit|delete|remove|discard|buy|pay|purchase|order|checkout|confirm|publish|"
                           r"post|transfer|uninstall|format|erase|wipe|sign out|log out|accept|agree|install)\b", re.I)
INTERACTIVE = {"Button", "MenuItem", "ListItem", "TabItem", "Hyperlink", "CheckBox", "RadioButton", "TreeItem",
               "ComboBox", "SplitButton", "Edit", "Document", "MenuBar", "DataItem"}
READABLE = {"Text", "Document", "Edit", "ListItem", "DataItem", "Hyperlink", "TreeItem", "Group"}

_local = threading.local()
_snapshot: list = []


def control_risk(name: str) -> Risk:
    return Risk.HIGH if RISKY_CONTROL.search(name or "") else Risk.LOW


def _auto():
    import uiautomation as auto
    if not getattr(_local, "init", None):
        _local.init = auto.UIAutomationInitializerInThread(debug=False)   # keep COM initialised on this thread
    return auto


def _root(window: str | None):
    auto = _auto()
    import win32gui
    if window:
        from automation.window_manager import _best
        hwnd = _best(window).hwnd
    else:
        hwnd = win32gui.GetForegroundWindow()
    return auto.ControlFromHandle(hwnd)


def _ctype(ctrl) -> str:
    return ctrl.ControlTypeName.replace("Control", "")


def _value(ctrl) -> str:
    try:
        return ctrl.GetValuePattern().Value or ""
    except Exception:
        return ""


def _walk(root, max_depth: int = 18, limit: int = 3000):
    auto = _auto()
    count = 0
    for ctrl, _depth in auto.WalkControl(root, includeTop=False, maxDepth=max_depth):
        count += 1
        if count > limit:
            return
        yield ctrl


def list_controls(window: str | None = None, filter: str = "", max_items: int = 120) -> dict:
    global _snapshot
    root = _root(window)
    items, snap = [], []
    for ctrl in _walk(root):
        t = _ctype(ctrl)
        if t not in INTERACTIVE:
            continue
        try:
            if ctrl.IsOffscreen or not ctrl.IsEnabled:
                continue
        except Exception:
            continue
        name = ctrl.Name or ""
        if not name and t not in ("Edit", "Document"):
            continue
        if filter and match_score(filter, name) < 0.5:
            continue
        snap.append(ctrl)
        entry = {"index": len(snap) - 1, "type": t, "name": name[:120]}
        if t in ("Edit", "ComboBox"):
            entry["value"] = _value(ctrl)[:80]
        items.append(entry)
        if len(items) >= max_items:
            break
    _snapshot = snap
    return {"window": root.Name, "controls": items,
            "note": "Use click_control with an index from this list, or with a control name."}


def _find(name: str | None, index: int | None, window: str | None, control_type: str | None):
    if index is not None:
        if not 0 <= index < len(_snapshot):
            raise LookupError("That control index is from an old list; call list_controls again.")
        return _snapshot[index]
    if not name:
        raise ValueError("Give a control name or an index from list_controls.")
    best, best_score = None, 0.0
    for ctrl in _walk(_root(window)):
        t = _ctype(ctrl)
        if control_type and t.lower() != control_type.lower():
            continue
        if t not in INTERACTIVE:
            continue
        s = match_score(name, ctrl.Name or "")
        if s > best_score:
            best, best_score = ctrl, s
            if s >= 0.99:
                break
    if best is None or best_score < 0.6:
        raise LookupError(f"No control named like '{name}' in this window. Call list_controls to see what's there.")
    return best


def name_for_risk(args: dict) -> str:
    if args.get("name"):
        return args["name"]
    idx = args.get("index")
    try:
        return _snapshot[idx].Name if idx is not None else ""
    except Exception:
        return "unknown control"


def click_control(name: str | None = None, index: int | None = None, window: str | None = None,
                  control_type: str | None = None, action: str = "click") -> dict:
    ctrl = _find(name, index, window, control_type)
    label, t = ctrl.Name, _ctype(ctrl)
    method = "mouse"
    if action == "click":
        for getter, call, m in (("GetInvokePattern", "Invoke", "invoke"), ("GetTogglePattern", "Toggle", "toggle"),
                                ("GetSelectionItemPattern", "Select", "select")):
            try:
                getattr(getattr(ctrl, getter)(), call)()
                method = m
                break
            except Exception:
                continue
        else:
            ctrl.Click(simulateMove=False)
    elif action == "double_click":
        ctrl.DoubleClick(simulateMove=False)
    elif action == "right_click":
        ctrl.RightClick(simulateMove=False)
    else:
        raise ValueError("action must be click, double_click or right_click")
    return {"clicked": label, "type": t, "action": action, "method": method}


def set_control_text(text: str, name: str | None = None, index: int | None = None, window: str | None = None) -> dict:
    if name is None and index is None:
        ctrl = _auto().GetFocusedControl()
    else:
        ctrl = _find(name, index, window, None)
    try:
        ctrl.GetValuePattern().SetValue(text)
        method = "value_pattern"
    except Exception:
        ctrl.Click(simulateMove=False)
        from automation.keyboard_mouse import type_text
        type_text(text)
        method = "typed"
    return {"field": ctrl.Name or _ctype(ctrl), "method": method, "verified_value": _value(ctrl)[:200]}


def read_window(window: str | None = None, max_chars: int = 10000) -> dict:
    root = _root(window)
    lines: list[str] = []
    for ctrl in _walk(root, limit=6000):
        if _ctype(ctrl) not in READABLE:
            continue
        try:
            if ctrl.IsOffscreen:
                continue
        except Exception:
            continue
        text = (ctrl.Name or "").strip() or _value(ctrl).strip()
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    body = "\n".join(lines)
    return {"window": root.Name, "text": body[:max_chars], "truncated": len(body) > max_chars,
            "note": "Only text exposed through Windows accessibility is visible; some apps expose little."}


def drag_control(source: str, target: str, window: str | None = None) -> dict:
    import pyautogui
    a = _find(source, None, window, None).BoundingRectangle
    b = _find(target, None, window, None).BoundingRectangle
    pyautogui.moveTo((a.left + a.right) // 2, (a.top + a.bottom) // 2, duration=0.2)
    pyautogui.dragTo((b.left + b.right) // 2, (b.top + b.bottom) // 2, duration=0.6, button="left")
    return {"dragged": source, "onto": target}


def mouse_click(button: str = "left", double: bool = False) -> dict:
    import pyautogui
    if double:
        pyautogui.doubleClick(button=button)
    else:
        pyautogui.click(button=button)
    x, y = pyautogui.position()
    return {"clicked": button, "double": double, "at": [x, y]}
