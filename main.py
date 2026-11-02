"""ROVEN entry point: python main.py  (or pythonw main.py for no console window)."""
from __future__ import annotations

import logging
import os
import queue
import sys
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if len(sys.argv) >= 3 and sys.argv[1] == "--run-script":
    # Lets the installed ROVEN.exe run Python scripts ROVEN writes (no separate Python install needed).
    import runpy
    sys.argv = [sys.argv[2]]
    runpy.run_path(sys.argv[0], run_name="__main__")
    sys.exit(0)

import customtkinter as ctk  # noqa: E402

from config import LOG_PATH, ensure_app_dir, load_settings, save_settings  # noqa: E402

_MUTEX = None


def setup_logging() -> None:
    ensure_app_dir()
    handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stdout:
        root.addHandler(logging.StreamHandler(sys.stdout))


def single_instance() -> bool:
    global _MUTEX
    if sys.platform != "win32":
        return True
    import ctypes
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ROVEN_SingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def get_api_key(root, provider: str) -> str | None:
    from security.credentials import get_secret, set_secret
    secret, env, label = {"gemini": ("gemini_api_key", "GEMINI_API_KEY", "Google Gemini"),
                          "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic")}[provider]
    key = get_secret(secret) or os.environ.get(env)
    if key:
        return key
    key = ctk.CTkInputDialog(title="ROVEN setup",
                             text=f"Enter your {label} API key.\nIt is stored in Windows Credential Manager.").get_input()
    if key and key.strip():
        set_secret(secret, key.strip())
        return key.strip()
    return None


def main() -> None:
    setup_logging()
    log = logging.getLogger("roven")
    if not single_instance():
        log.info("ROVEN is already running")
        return
    settings = load_settings()
    from automation.screen import enable_dpi_awareness
    enable_dpi_awareness()             # before any window exists, so screen clicks land precisely
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.withdraw()
    root.title("ROVEN")

    if not settings.onboarded:
        from interface.onboarding import Onboarding
        wizard = Onboarding(root, settings)
        root.wait_window(wizard)
        if not wizard.completed:
            return
    api_key = get_api_key(root, settings.llm_provider)
    if not api_key:
        from tkinter import messagebox
        messagebox.showerror("ROVEN", "An AI API key is required. Run ROVEN again to enter it.")
        return

    from core.assistant import Assistant
    from interface.dashboard import Dashboard
    from interface.floating_dock import FloatingDock
    from interface.results_window import ResultsWindow
    from interface.system_tray import Tray

    ui_q: queue.Queue = queue.Queue()
    assistant = Assistant(settings, ui_q, api_key)
    dock = FloatingDock(root, mic_level=lambda: assistant.mic.level,
                        on_confirm=assistant.answer_confirmation,
                        on_click=lambda: ui_q.put(("cmd", "dashboard")))
    state = {"dashboard": None}

    def open_dashboard() -> None:
        d = state["dashboard"]
        if d is None or not d.winfo_exists():
            state["dashboard"] = Dashboard(root, assistant)
        else:
            d.deiconify()
            d.lift()

    def toggle_privacy() -> None:
        assistant.set_privacy(not settings.privacy_mode)
        save_settings(settings)

    def quit_app() -> None:
        assistant.shutdown()
        assistant.join(timeout=5)
        tray.stop()
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        root.after(300, root.destroy)

    def open_today_log() -> None:
        path = assistant.chat_log.today_path()
        if path.exists():
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            dock.set_state("error", "No conversation logged today yet.")
            dock.set_state("standby")

    tray = Tray(on_activate=assistant.activate, on_dashboard=lambda: ui_q.put(("cmd", "dashboard")),
                on_open_log=lambda: ui_q.put(("cmd", "log")),
                on_toggle_privacy=toggle_privacy, is_privacy=lambda: settings.privacy_mode,
                on_stop=assistant.emergency_stop, on_quit=lambda: ui_q.put(("cmd", "quit")))

    try:
        import keyboard
        keyboard.add_hotkey(settings.emergency_hotkey, assistant.emergency_stop)
        keyboard.add_hotkey(settings.manual_hotkey, assistant.activate)
    except Exception:
        log.warning("Global hotkeys unavailable", exc_info=True)

    import pyautogui
    pyautogui.FAILSAFE = True   # slam the mouse into a screen corner to abort automation

    def handle(kind, payload) -> bool:
        """Apply one message from the assistant to the UI. Returns False when ROVEN should exit."""
        if kind == "cmd":
            if payload == "dashboard":
                open_dashboard()
            elif payload == "log":
                open_today_log()
            elif payload == "quit":
                quit_app()
                return False
        elif kind == "transcript":
            dock.set_detail(payload)
        elif kind == "info":
            log.info(payload)
        elif kind == "show":
            ResultsWindow(root, payload["title"], payload["columns"], payload["rows"], payload["text"])
        else:
            dock.set_state(kind, payload)
        d = state["dashboard"]
        if d is not None and d.winfo_exists() and kind != "cmd":
            d.refresh_status(kind)
        return True

    def pump() -> None:
        keep_running = True
        try:
            while keep_running:
                try:
                    kind, payload = ui_q.get_nowait()
                except queue.Empty:
                    break
                try:
                    keep_running = handle(kind, payload)
                except Exception:
                    # A display problem must never freeze the dock or stop ROVEN from working.
                    log.exception("UI update failed for %s", kind)
        finally:
            if keep_running:
                root.after(40, pump)

    assistant.start()
    tray.start()
    root.after(40, pump)
    log.info("ROVEN started")
    root.mainloop()


if __name__ == "__main__":
    main()
