"""Keyboard and scroll control with risk escalation for terminals and Enter."""
from __future__ import annotations

import time

from security.permission_manager import Risk

TERMINAL_PROCESSES = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe",
                      "bash.exe", "wsl.exe", "conhost.exe", "mintty.exe", "openconsole.exe"}


def foreground_process() -> str:
    try:
        import psutil
        import win32gui
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def foreground_title() -> str:
    try:
        import win32gui
        return win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except Exception:
        return ""


def typing_risk(args: dict) -> Risk:
    if foreground_process() in TERMINAL_PROCESSES:
        return Risk.HIGH           # typing into a shell == running commands
    if "\n" in args.get("text", ""):
        return Risk.MEDIUM         # newline may submit/send
    return Risk.LOW


def keys_risk(args: dict) -> Risk:
    keys = [k.lower() for k in args.get("keys", [])]
    if foreground_process() in TERMINAL_PROCESSES:
        return Risk.HIGH
    if "enter" in keys or "return" in keys or ("alt" in keys and "f4" in keys):
        return Risk.MEDIUM
    return Risk.LOW


def type_text(text: str) -> dict:
    import pyautogui
    import pyperclip
    if text.isascii():
        pyautogui.write(text, interval=0.01)
    else:  # pyautogui can't type Urdu/Hindi/CJK; paste via clipboard and restore it
        previous = pyperclip.paste()
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        pyperclip.copy(previous)
    return {"typed_characters": len(text), "into_window": foreground_title()}


def press_keys(keys: list[str]) -> dict:
    import pyautogui
    keys = [k.lower() for k in keys]
    bad = [k for k in keys if k not in pyautogui.KEYBOARD_KEYS]
    if bad:
        raise ValueError(f"Unknown key names: {bad}")
    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)
    return {"pressed": "+".join(keys), "window": foreground_title()}


def scroll(direction: str, amount: int = 5) -> dict:
    import pyautogui
    pyautogui.scroll((amount if direction == "up" else -amount) * 120)
    return {"scrolled": direction, "window": foreground_title()}
