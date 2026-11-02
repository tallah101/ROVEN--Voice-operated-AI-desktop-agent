"""Screen vision for full PC control: ROVEN takes a screenshot, the AI looks at it, then clicks or types at
what it sees — works in any app, even ones that expose nothing to UI Automation. (Screen capture only;
no webcam.)"""
from __future__ import annotations

import io
import threading

from core.tool_registry import ToolImage

_state = {"scale": 1.0, "left": 0, "top": 0, "width": 0, "height": 0, "monitor": 1}
_lock = threading.Lock()


def enable_dpi_awareness() -> None:
    """Without this, clicks land in the wrong place on scaled (125%/150%) displays."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def capture(monitor: int = 1, max_width: int = 1366) -> ToolImage:
    import mss
    from PIL import Image
    with mss.mss() as sct:
        monitors = sct.monitors
        if not 1 <= monitor < len(monitors):
            monitor = 1
        m = monitors[monitor]
        raw = sct.grab(m)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    scale = min(1.0, max_width / img.width)
    if scale < 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    with _lock:
        _state.update(scale=scale, left=m["left"], top=m["top"], width=img.width, height=img.height, monitor=monitor)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=72, optimize=True)
    return ToolImage(buf.getvalue(), "image/jpeg",
                     f"Screenshot of monitor {monitor} ({len(monitors) - 1} monitor(s) total), {img.width}x{img.height} px. "
                     "Give click coordinates in this image's pixels.")


def to_screen(x: float, y: float) -> tuple[int, int]:
    with _lock:
        if not _state["width"]:
            raise RuntimeError("Take a screenshot with look_at_screen first, so coordinates have a reference.")
        if not (0 <= x <= _state["width"] and 0 <= y <= _state["height"]):
            raise ValueError(f"({x}, {y}) is outside the last screenshot ({_state['width']}x{_state['height']}).")
        return int(_state["left"] + x / _state["scale"]), int(_state["top"] + y / _state["scale"])


def click_at(x: float, y: float, target: str, button: str = "left", clicks: int = 1) -> dict:
    import pyautogui
    sx, sy = to_screen(x, y)
    pyautogui.click(sx, sy, clicks=clicks, interval=0.08, button=button)
    return {"clicked": target, "button": button, "clicks": clicks, "screen_point": [sx, sy],
            "note": "Take another screenshot if you need to confirm the result."}


def move_to(x: float, y: float) -> dict:
    import pyautogui
    sx, sy = to_screen(x, y)
    pyautogui.moveTo(sx, sy, duration=0.15)
    return {"moved_to": [sx, sy]}


def drag(x1: float, y1: float, x2: float, y2: float, target: str) -> dict:
    import pyautogui
    a, b = to_screen(x1, y1), to_screen(x2, y2)
    pyautogui.moveTo(*a, duration=0.15)
    pyautogui.dragTo(*b, duration=0.6, button="left")
    return {"dragged": target, "from": list(a), "to": list(b)}


def save_screenshot(folder: str | None = None) -> dict:
    import mss
    from datetime import datetime

    from automation.documents import unique_path
    from core.paths import known_folder
    from security.action_validator import safe_user_path
    dest_dir = safe_user_path(folder) if folder else known_folder("pictures") / "Screenshots"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(dest_dir / f"Screenshot {datetime.now():%Y-%m-%d %H-%M-%S}.png")
    with mss.mss() as sct:
        sct.shot(mon=-1, output=str(dest))
    return {"saved": str(dest), "verified": dest.exists()}
