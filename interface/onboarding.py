"""First-run setup: API key, microphone test, wake word, auto-start. Integrations are offered afterwards."""
from __future__ import annotations

import sys
from tkinter import filedialog

import customtkinter as ctk
import numpy as np

from config import MODELS_DIR, save_settings
from security.credentials import get_secret, set_secret


class Onboarding(ctk.CTkToplevel):
    def __init__(self, master, settings) -> None:
        super().__init__(master)
        self.s = settings
        self.title("Welcome to ROVEN")
        self.geometry("620x480")
        self.resizable(False, False)
        self.completed = False
        self._stream = None
        self.level = 0.0
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=28, pady=24)
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=28, pady=(0, 20))
        self.back = ctk.CTkButton(nav, text="Back", width=90, command=lambda: self.show(self.step - 1))
        self.back.pack(side="left")
        self.next = ctk.CTkButton(nav, text="Next", width=120, command=self._next)
        self.next.pack(side="right")
        self.steps = [self._welcome, self._api_key, self._microphone, self._wake, self._startup]
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.show(0)
        self.grab_set()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _title(self, text, sub=""):
        ctk.CTkLabel(self.body, text=text, font=ctk.CTkFont("Segoe UI", 22, "bold"), anchor="w").pack(fill="x")
        if sub:
            ctk.CTkLabel(self.body, text=sub, anchor="w", justify="left", wraplength=560,
                         text_color="#9aa1ad").pack(fill="x", pady=(6, 16))

    def show(self, i):
        self._stop_mic()
        self.step = max(0, min(i, len(self.steps) - 1))
        self._clear()
        self.steps[self.step]()
        self.back.configure(state="normal" if self.step else "disabled")
        self.next.configure(text="Finish" if self.step == len(self.steps) - 1 else "Next")

    def _next(self):
        if self.step == 1 and not self._save_key():
            return
        if self.step == len(self.steps) - 1:
            self._finish()
        else:
            self.show(self.step + 1)

    def _welcome(self):
        self._title("Hi, I'm ROVEN.", "I run quietly in the background. Say “Roven” and tell me what you need — in English, "
                    "Urdu, Roman Urdu or another language. This setup takes about two minutes.")

    SECRETS = {"Google Gemini (free tier)": ("gemini", "gemini_api_key", "AIza…"),
               "Anthropic Claude": ("anthropic", "anthropic_api_key", "sk-ant-…")}

    def _api_key(self):
        self._title("AI key", "Choose the AI that powers ROVEN and paste its API key. Gemini keys come from "
                    "aistudio.google.com, Claude keys from console.anthropic.com. Keys are stored in Windows "
                    "Credential Manager, never in a file.")
        current = next((k for k, v in self.SECRETS.items() if v[0] == self.s.llm_provider), "Google Gemini (free tier)")
        self.provider_var = ctk.StringVar(value=current)
        ctk.CTkOptionMenu(self.body, variable=self.provider_var, values=list(self.SECRETS), width=520,
                          command=lambda _: self.show(1)).pack(anchor="w", pady=(0, 10))
        self.key = ctk.CTkEntry(self.body, show="•", width=520,
                                placeholder_text="Already saved" if self._has_key() else self.SECRETS[current][2])
        self.key.pack(anchor="w")
        self.key_err = ctk.CTkLabel(self.body, text="", text_color="#f87171")
        self.key_err.pack(anchor="w", pady=6)

    def _provider(self):
        return self.SECRETS[self.provider_var.get()] if hasattr(self, "provider_var") else ("anthropic", "anthropic_api_key", "")

    def _has_key(self):
        try:
            return bool(get_secret(self._provider()[1]))
        except Exception:
            return False

    def _save_key(self) -> bool:
        provider, secret, _ = self._provider()
        self.s.llm_provider = provider
        k = self.key.get().strip()
        if k:
            set_secret(secret, k)
            return True
        if self._has_key():
            return True
        self.key_err.configure(text="A key is required.")
        return False

    def _microphone(self):
        from speech.microphone import Microphone
        self._title("Microphone", "Pick your microphone and say something — the bar should move.")
        try:
            devices = ["Default"] + [f"{i}: {n}" for i, n in Microphone.list_devices()]
        except Exception as exc:
            devices = ["Default"]
            ctk.CTkLabel(self.body, text=f"Audio error: {exc}", text_color="#f87171").pack(anchor="w")
        cur = next((d for d in devices if d.startswith(f"{self.s.mic_device}:")), "Default")
        self.mic_var = ctk.StringVar(value=cur)
        ctk.CTkOptionMenu(self.body, variable=self.mic_var, values=devices, width=520,
                          command=lambda _: self._start_mic()).pack(anchor="w")
        self.bar = ctk.CTkProgressBar(self.body, width=520)
        self.bar.pack(anchor="w", pady=20)
        self.bar.set(0)
        self._start_mic()
        self._tick()

    def _start_mic(self):
        self._stop_mic()
        v = self.mic_var.get()
        self.s.mic_device = None if v == "Default" else int(v.split(":")[0])
        try:
            import sounddevice as sd

            def cb(indata, frames, t, status):
                self.level = min(1.0, float(np.sqrt(np.mean(indata.astype(np.float32) ** 2))) / 4000)
            self._stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", device=self.s.mic_device, callback=cb)
            self._stream.start()
        except Exception:
            self._stream = None

    def _stop_mic(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _tick(self):
        if self.step == 2 and self.winfo_exists():
            self.bar.set(self.level)
            self.after(60, self._tick)

    def _wake(self):
        self._title("Wake word", "Without a trained model ROVEN listens for “Roven” with a small local speech model "
                    "(works out of the box, a bit more CPU). For best accuracy, train a custom openWakeWord model "
                    f"(README → Wake word) and choose it here. Models folder: {MODELS_DIR}")
        self.wake_var = ctk.StringVar(value=self.s.wake_engine if self.s.wake_model_path else "whisper_keyword")
        ctk.CTkOptionMenu(self.body, variable=self.wake_var, values=["whisper_keyword", "openwakeword", "porcupine"]).pack(anchor="w")
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=10)
        self.wake_path = ctk.CTkEntry(row, width=420, placeholder_text="Model file (.onnx or .ppn)")
        self.wake_path.insert(0, self.s.wake_model_path)
        self.wake_path.pack(side="left")
        ctk.CTkButton(row, text="Browse…", width=90, command=self._pick_wake).pack(side="left", padx=8)

    def _pick_wake(self):
        p = filedialog.askopenfilename(initialdir=str(MODELS_DIR), filetypes=[("Wake models", "*.onnx *.tflite *.ppn")])
        if p:
            self.wake_path.delete(0, "end")
            self.wake_path.insert(0, p)
        self.s.wake_engine = self.wake_var.get()

    def _startup(self):
        self.s.wake_engine = getattr(self, "wake_var", ctk.StringVar(value=self.s.wake_engine)).get()
        if hasattr(self, "wake_path"):
            self.s.wake_model_path = self.wake_path.get().strip()
        self._title("Start with Windows", "ROVEN can start automatically when you sign in, so it's always ready. "
                    "Connect Gmail, Slack and ClickUp any time from the dashboard (click the dock or the tray icon).")
        self.auto_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.body, text="Start ROVEN when I sign in to Windows", variable=self.auto_var).pack(anchor="w")
        ctk.CTkLabel(self.body, text="Shortcuts:  Ctrl+Alt+Space = activate   •   Ctrl+Alt+Shift+X = emergency stop",
                     text_color="#9aa1ad").pack(anchor="w", pady=20)

    def _finish(self):
        if sys.platform == "win32":
            from scripts import install_startup
            try:
                install_startup.enable() if self.auto_var.get() else install_startup.disable()
            except Exception:
                pass
        self.s.onboarded = True
        save_settings(self.s)
        self.completed = True
        self._stop_mic()
        self.destroy()

    def _cancel(self):
        self._stop_mic()
        self.destroy()
