"""System tray icon (pystray, own thread). Callbacks must be thread-safe."""
from __future__ import annotations

from PIL import Image, ImageDraw


def _icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(124, 156, 255, 255))
    d.text((24, 18), "R", fill=(20, 22, 27, 255))
    return img


class Tray:
    def __init__(self, on_activate, on_dashboard, on_open_log, on_toggle_privacy, is_privacy, on_stop, on_quit) -> None:
        self.cb = dict(activate=on_activate, dashboard=on_dashboard, log=on_open_log, privacy=on_toggle_privacy,
                       is_privacy=is_privacy, stop=on_stop, quit=on_quit)
        self.icon = None

    def start(self) -> None:
        import pystray
        Item = pystray.MenuItem
        menu = pystray.Menu(
            Item("Activate ROVEN", lambda: self.cb["activate"](), default=True),
            Item("Dashboard", lambda: self.cb["dashboard"]()),
            Item("Open today's conversation log", lambda: self.cb["log"]()),
            Item("Privacy mode (mic off)", lambda: self.cb["privacy"](), checked=lambda i: self.cb["is_privacy"]()),
            Item("Emergency stop", lambda: self.cb["stop"]()),
            pystray.Menu.SEPARATOR,
            Item("Quit ROVEN", lambda: self.cb["quit"]()),
        )
        self.icon = pystray.Icon("ROVEN", _icon_image(), "ROVEN", menu)
        self.icon.run_detached()

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()
