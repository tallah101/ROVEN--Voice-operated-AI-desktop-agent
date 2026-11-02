"""ROVEN's island: a dark rectangle attached to the top edge of the screen, centred.

It drops down when ROVEN wakes, smoothly morphs its size as content changes (status → what you said →
the answer → a confirmation), and slides back up when done — like a rectangular Dynamic Island.
It never takes keyboard focus from the app you're using."""
from __future__ import annotations

import math
import sys
import tkinter as tk
from collections import deque

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageTk

KEY = "#010203"   # transparent key colour (Windows): only the island's shape is visible
C = {
    "bg": "#0b0c0f", "fg": "#f2f4f7", "muted": "#8e95a2",
    "accent": "#8ab4ff", "ok": "#5fe39a", "err": "#ff6b6b", "warn": "#ffc861", "idle": "#4b5160",
}
STATE = {   # label, colour key
    "wake": ("Listening", "accent"), "listening": ("Listening", "accent"),
    "transcribing": ("Understanding", "accent"), "processing": ("Thinking", "accent"),
    "executing": ("Working", "warn"), "speaking": ("Speaking", "ok"),
    "confirm": ("Allow this?", "warn"), "done": ("Done", "ok"), "error": ("Couldn't do that", "err"),
}
FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"


def _rgb(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _blend(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a, b = _rgb(c1), _rgb(c2)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class FloatingDock(ctk.CTkToplevel):
    # sizes in logical pixels (multiplied by the display scale, e.g. 1.25 at 125 %)
    W_COMPACT, W_WIDE, W_CONFIRM = 210, 440, 470
    H, H_TEXT1, H_TEXT2 = 42, 58, 76
    RADIUS = 18
    CHAR_PX = 6.9
    EASE = 0.26          # fraction of the remaining distance covered per frame (smooth ease-out)

    def __init__(self, master, mic_level, on_confirm, on_click) -> None:
        super().__init__(master)
        self.mic_level = mic_level
        self.on_confirm = on_confirm
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        if sys.platform == "win32":
            self.configure(fg_color=KEY)
            self.attributes("-transparentcolor", KEY)
        else:
            self.configure(fg_color=C["bg"])
        try:
            self.scale = float(self._get_window_scaling())
        except Exception:
            self.scale = 1.0

        self.island = ctk.CTkFrame(self, corner_radius=self.RADIUS, fg_color=C["bg"], border_width=0)
        self.island.pack(fill="both", expand=True)
        # square top corners: the island looks attached to the top edge of the screen
        self.top_fill = ctk.CTkFrame(self.island, fg_color=C["bg"], corner_radius=0, height=self.RADIUS + 2)
        self.top_fill.place(x=0, y=0, relwidth=1)

        row = ctk.CTkFrame(self.island, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=(14, 16), pady=(4, 7))
        self.orb = tk.Label(row, bg=C["bg"], bd=0, highlightthickness=0)
        self.orb.pack(side="left")
        self.wave = tk.Label(row, bg=C["bg"], bd=0, highlightthickness=0)
        self.wave.pack(side="left", padx=(7, 10))
        self._imgs: dict = {}

        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        self.text_frame = text
        self.status = ctk.CTkLabel(text, text="", anchor="w", height=18, text_color=C["fg"],
                                   font=ctk.CTkFont(FONT, 13, "bold"))
        self.status.pack(fill="x")
        self.detail = ctk.CTkLabel(text, text="", anchor="w", justify="left", height=16,
                                   text_color=C["muted"], font=ctk.CTkFont(FONT, 12))

        self.buttons = ctk.CTkFrame(row, fg_color="transparent")
        ctk.CTkButton(self.buttons, text="Yes", width=50, height=26, corner_radius=8, fg_color=C["ok"],
                      hover_color=_blend(C["ok"], "#ffffff", 0.2), text_color="#0b0d10",
                      font=ctk.CTkFont(FONT, 12, "bold"), command=lambda: self.on_confirm(True)).pack(side="left", padx=2)
        ctk.CTkButton(self.buttons, text="No", width=50, height=26, corner_radius=8, fg_color="#24272f",
                      hover_color="#30343e", text_color=C["fg"], font=ctk.CTkFont(FONT, 12, "bold"),
                      command=lambda: self.on_confirm(False)).pack(side="left", padx=2)

        for w in (self.island, self.top_fill, row, self.orb, self.wave, text, self.status, self.detail):
            w.bind("<Button-1>", lambda e: on_click())

        self.state_name = "standby"
        self.detail_text = ""
        self.levels = deque([0.0] * 7, maxlen=7)
        self.phase = 0.0
        self.visible = False
        self._hide_job = None
        self._tween_running = False
        self._target = [float(self.W_COMPACT), float(self.H), -float(self.H) - 6]   # width, height, top
        self._current = list(self._target)
        self._apply_geometry()
        self.withdraw()
        self.after(200, self._no_activate)
        self.after(33, self._animate)

    # ---- geometry ----------------------------------------------------------------------------
    def _apply_geometry(self) -> None:
        """Set size and position in physical pixels, centred on the primary screen."""
        w, h, top = self._current
        pw, ph = round(w * self.scale), round(h * self.scale)
        x = round((self.winfo_screenwidth() - pw) / 2)
        y = round(top * self.scale)
        tk.Toplevel.wm_geometry(self, f"{pw}x{ph}+{x}+{y}")     # bypass CustomTkinter's (size-only) scaling

    def _animate_to(self, w: float, h: float, top: float) -> None:
        self._target = [float(w), float(h), float(top)]
        if not self._tween_running:
            self._tween_running = True
            self._tween()

    def _tween(self) -> None:
        settled = True
        for i in range(3):
            diff = self._target[i] - self._current[i]
            if abs(diff) < 0.6:
                self._current[i] = self._target[i]
            else:
                self._current[i] += diff * self.EASE
                settled = False
        self._apply_geometry()
        if not settled:
            self.after(16, self._tween)
            return
        self._tween_running = False
        if not self.visible:
            self.withdraw()

    def _layout(self) -> None:
        confirm = self.state_name == "confirm"
        w = self.W_CONFIRM if confirm else (self.W_WIDE if self.detail_text else self.W_COMPACT)
        wrap = w - (250 if confirm else 150)
        per_line = max(10, int(wrap / self.CHAR_PX))
        if self.detail_text:
            if len(self.detail_text) > per_line * 2:
                self.detail_text = self.detail_text[:per_line * 2 - 1].rstrip() + "…"
            self.detail.configure(text=self.detail_text, wraplength=wrap)
            self.detail.pack(fill="x")
            h = self.H_TEXT2 if len(self.detail_text) > per_line else self.H_TEXT1
        else:
            self.detail.pack_forget()
            h = self.H
        if confirm:
            self.buttons.pack(side="right", padx=(8, 0), before=self.text_frame)
        else:
            self.buttons.pack_forget()
        top = 0.0 if self.visible else -h - 6
        self._animate_to(w, h, top)

    def _no_activate(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)  # NOACTIVATE | TOOLWINDOW

    # ---- state -----------------------------------------------------------------------------
    def set_state(self, state: str, text: str | None = None) -> None:
        if self._hide_job:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        if state == "standby":
            delay = 3200 if self.state_name == "error" else 900
            self._hide_job = self.after(delay, self._hide)
            return
        prev, self.state_name = self.state_name, state
        label, colour = STATE.get(state, (state.title(), "fg"))
        self.status.configure(text=label, text_color=C["fg"] if colour in ("accent", "ok") else C[colour])
        if text is not None:
            self._set_text(text)
        elif state == "listening" and prev not in ("wake", "listening"):
            self._set_text("")
        elif state == "done" and prev == "error":
            self._set_text("")
        if not self.visible:
            self._show()
        self._layout()

    def set_detail(self, text: str) -> None:
        self._set_text(text)
        self._layout()

    def _set_text(self, text: str) -> None:
        text = " ".join((text or "").split())
        self.detail_text = text if len(text) <= 140 else text[:137].rstrip() + "…"
        self.detail.configure(text=self.detail_text)

    def _show(self) -> None:
        self.visible = True
        self.attributes("-alpha", 0.98)
        if self._current[2] < 0:                      # start just above the screen edge
            self._current[2] = -self._current[1] - 6
        self._apply_geometry()
        self.deiconify()
        self.lift()

    def _hide(self) -> None:
        self._hide_job = None
        self.state_name = "standby"
        if self.visible:
            self.visible = False
            self._animate_to(self._current[0], self._current[1], -self._current[1] - 6)   # slide up out of view
            self.after(600, self._reset_text)

    def _reset_text(self) -> None:
        if not self.visible:
            self.detail_text = ""
            self.detail.configure(text="")
            self.detail.pack_forget()
            self.buttons.pack_forget()
            self._target[0], self._target[1] = float(self.W_COMPACT), float(self.H)
            self._current[0], self._current[1] = float(self.W_COMPACT), float(self.H)
            self._current[2] = self._target[2] = -float(self.H) - 6

    # ---- animation of the orb and waveform ---------------------------------------------------
    def _colour(self) -> str:
        return C[STATE[self.state_name][1]] if self.state_name in STATE else C["idle"]

    def _animate(self) -> None:
        if self.visible:
            self.phase += 0.18
            self._draw_orb()
            self._draw_wave()
        self.after(33, self._animate)

    def _show_image(self, widget, key: str, img: Image.Image) -> None:
        photo = ImageTk.PhotoImage(img)
        self._imgs[key] = photo
        widget.configure(image=photo)

    def _draw_orb(self) -> None:
        st = self.state_name
        if st in ("wake", "listening", "confirm"):
            pulse = min(1.0, self.mic_level() * 2.2)
        elif st in ("processing", "transcribing", "executing", "speaking"):
            pulse = 0.5 + 0.5 * math.sin(self.phase * 1.4)
        else:
            pulse = 0.0
        self._show_image(self.orb, "orb", render_orb(self._colour(), pulse, self.scale))

    def _draw_wave(self) -> None:
        n = 7
        st = self.state_name
        if st in ("wake", "listening", "confirm"):
            self.levels.append(min(1.0, self.mic_level() * 1.8))
            amps = list(self.levels)
        elif st in ("processing", "transcribing", "executing"):
            amps = [0.25 + 0.35 * (1 + math.sin(self.phase - i * 0.7)) / 2 for i in range(n)]
        elif st == "speaking":
            amps = [0.2 + 0.8 * abs(math.sin(self.phase * 1.3 + i * 1.1)) * (0.6 + 0.4 * math.sin(self.phase * 0.5 + i))
                    for i in range(n)]
        else:
            amps = [0.0] * n
        self._show_image(self.wave, "wave", render_wave(amps, self._colour(), self.scale))


SS = 4   # supersampling factor for smooth (anti-aliased) edges


def render_orb(colour: str, pulse: float, scale: float = 1.0) -> Image.Image:
    """A glowing dot: soft halo that breathes with `pulse` (0–1) around a solid core with a highlight."""
    size = max(8, round(20 * scale))
    big = size * SS
    mid = big / 2
    bg, col = _rgb(C["bg"]), _rgb(colour)
    img = Image.new("RGB", (big, big), bg)
    glow = Image.new("L", (big, big), 0)
    g = ImageDraw.Draw(glow)
    r_glow = big * (0.30 + 0.16 * pulse)
    g.ellipse((mid - r_glow, mid - r_glow, mid + r_glow, mid + r_glow), fill=int(110 + 70 * pulse))
    glow = glow.filter(ImageFilter.GaussianBlur(big * 0.09))
    img.paste(Image.new("RGB", (big, big), col), (0, 0), glow)
    d = ImageDraw.Draw(img)
    r = big * 0.22
    d.ellipse((mid - r, mid - r, mid + r, mid + r), fill=col)
    hl = tuple(round(c + (255 - c) * 0.6) for c in col)
    hr, hx, hy = big * 0.065, mid - r * 0.38, mid - r * 0.38
    d.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=hl)
    return img.resize((size, size), Image.LANCZOS)


def render_wave(amps: list[float], colour: str, scale: float = 1.0) -> Image.Image:
    """Seven rounded bars, brightest in the middle."""
    w, h = max(10, round(34 * scale)), max(8, round(18 * scale))
    W, H = w * SS, h * SS
    bg, col = _rgb(C["bg"]), _rgb(colour)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    n = len(amps)
    gap = W / n
    bar_w = gap * 0.46
    for i, a in enumerate(amps):
        fade = 0.18 + 0.82 * (1 - abs(i - (n - 1) / 2) / ((n - 1) / 2)) ** 0.6
        fill = tuple(round(b + (c - b) * fade) for b, c in zip(bg, col))
        bar_h = max(bar_w, H * max(0.0, min(1.0, a)))
        x = gap * i + (gap - bar_w) / 2
        d.rounded_rectangle((x, (H - bar_h) / 2, x + bar_w, (H + bar_h) / 2), radius=bar_w / 2, fill=fill)
    return img.resize((w, h), Image.LANCZOS)
