"""Dashboard: status, activity log, memory manager and settings."""
from __future__ import annotations

import threading
from tkinter import filedialog

import customtkinter as ctk

from config import save_settings
from security.credentials import set_secret


class Dashboard(ctk.CTkToplevel):
    def __init__(self, master, assistant) -> None:
        super().__init__(master)
        self.a = assistant
        self.s = assistant.settings
        self.title("ROVEN Dashboard")
        self.geometry("860x620")
        self.status = ctk.CTkLabel(self, text="", anchor="w", font=ctk.CTkFont("Segoe UI", 14, "bold"))
        self.status.pack(fill="x", padx=18, pady=(14, 4))
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=12, pady=8)
        self._activity(tabs.add("Activity"))
        self._tasks(tabs.add("Tasks"))
        self._integrations(tabs.add("Integrations"))
        self._memory(tabs.add("Memory"))
        self._settings(tabs.add("Settings"))
        self.refresh_status()

    def refresh_status(self, state: str | None = None) -> None:
        wake = self.a.wake.name if self.a.wake else "starting"
        mic = "off (privacy mode)" if self.s.privacy_mode else ("on" if self.a.mic.running else "starting")
        self.status.configure(text=f"Wake engine: {wake}   •   Microphone: {mic}   •   AI: {self._ai_label()}"
                                   + (f"   •   {state}" if state else ""))

    def _ai_label(self) -> str:
        if self.s.llm_provider == "gemini":
            client = getattr(self.a.engine, "client", None)
            return f"Gemini ({getattr(client, 'active_model', None) or self.s.gemini_model})"
        return f"Claude ({self.s.llm_model})"

    # ---- activity ------------------------------------------------------------------------------
    def _activity(self, tab) -> None:
        self.log_box = ctk.CTkTextbox(tab, font=ctk.CTkFont("Consolas", 12))
        self.log_box.pack(fill="both", expand=True, pady=(0, 6))
        ctk.CTkButton(tab, text="Refresh", width=100, command=self.load_activity).pack(anchor="e")
        self.load_activity()

    def load_activity(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        for row in self.a.audit.recent(200):
            line = f"{row['ts']}  {row['event']:<15} {row['tool'] or '':<20} {row['status'] or '':<7} {(row['detail'] or row['args'] or '')[:140]}\n"
            self.log_box.insert("end", line)
        self.log_box.configure(state="disabled")

    # ---- task history (workflow store) ---------------------------------------------------------------
    def _tasks(self, tab) -> None:
        self.task_box = ctk.CTkTextbox(tab, font=ctk.CTkFont("Consolas", 12))
        self.task_box.pack(fill="both", expand=True, pady=(0, 6))
        ctk.CTkButton(tab, text="Refresh", width=100, command=self.load_tasks).pack(anchor="e")
        self.load_tasks()

    def load_tasks(self) -> None:
        self.task_box.configure(state="normal")
        self.task_box.delete("1.0", "end")
        for w in self.a.workflow_store.recent(60):
            self.task_box.insert("end", f"{w['started']}  {w['status']:<11} {w['request'][:110]}\n")
        self.task_box.configure(state="disabled")

    # ---- integrations ----------------------------------------------------------------------------
    def _integrations(self, tab) -> None:
        f = ctk.CTkScrollableFrame(tab)
        f.pack(fill="both", expand=True)
        f.grid_columnconfigure(1, weight=1)
        self.int_status = {}
        r = 0

        def header(text):
            nonlocal r
            ctk.CTkLabel(f, text=text, font=ctk.CTkFont("Segoe UI", 14, "bold"), anchor="w").grid(
                row=r, column=0, columnspan=3, sticky="w", padx=8, pady=(16, 4))
            r += 1
            lbl = ctk.CTkLabel(f, text="", anchor="w", text_color="#9aa1ad")
            lbl.grid(row=r, column=0, columnspan=3, sticky="w", padx=8)
            r += 1
            return lbl

        # Google
        self.int_status["google"] = header("Google — Gmail, Calendar, Drive")
        self.e_gclient = ctk.CTkEntry(f, placeholder_text="OAuth client JSON (Desktop app) — see README")
        self.e_gclient.insert(0, self.s.google_client_secrets_path)
        self.e_gclient.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        ctk.CTkButton(f, text="Browse…", width=90, command=self._pick_google_json).grid(row=r, column=2, padx=8)
        r += 1
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.grid(row=r, column=0, columnspan=3, sticky="w", padx=8)
        ctk.CTkButton(row, text="Connect Google", command=self._connect_google).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="Disconnect", fg_color="#7f1d1d", command=lambda: self._disconnect("google")).pack(side="left")
        r += 1
        self.e_domains = ctk.CTkEntry(f, placeholder_text="Trusted internal email domains, comma separated (optional)")
        self.e_domains.insert(0, ", ".join(self.s.trusted_email_domains))
        self.e_domains.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        r += 1

        # Slack
        self.int_status["slack"] = header("Slack")
        self.e_slack = ctk.CTkEntry(f, show="•", placeholder_text="User OAuth token (xoxp-…)")
        self.e_slack.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        ctk.CTkButton(f, text="Save", width=90, command=lambda: self._connect_token("slack")).grid(row=r, column=2, padx=8)
        r += 1
        self.e_brief = ctk.CTkEntry(f, placeholder_text="Channels for the daily briefing, e.g. mintsy, dev-team")
        self.e_brief.insert(0, ", ".join(self.s.slack_briefing_channels))
        self.e_brief.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        ctk.CTkButton(f, text="Disconnect", width=90, fg_color="#7f1d1d",
                      command=lambda: self._disconnect("slack")).grid(row=r, column=2, padx=8)
        r += 1

        # ClickUp
        self.int_status["clickup"] = header("ClickUp")
        self.e_clickup = ctk.CTkEntry(f, show="•", placeholder_text="Personal API token (pk_…)")
        self.e_clickup.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        ctk.CTkButton(f, text="Save", width=90, command=lambda: self._connect_token("clickup")).grid(row=r, column=2, padx=8)
        r += 1
        self.e_cuformat = ctk.CTkEntry(f, placeholder_text="Task title format")
        self.e_cuformat.insert(0, self.s.clickup_title_format)
        self.e_cuformat.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        ctk.CTkButton(f, text="Disconnect", width=90, fg_color="#7f1d1d",
                      command=lambda: self._disconnect("clickup")).grid(row=r, column=2, padx=8)
        r += 1
        ctk.CTkButton(f, text="Save options & check connections", command=self._save_integration_options).grid(
            row=r, column=0, columnspan=3, sticky="e", padx=8, pady=16)
        self._refresh_integrations(live=False)

    def _pick_google_json(self) -> None:
        path = filedialog.askopenfilename(title="Google OAuth client JSON", filetypes=[("JSON", "*.json")])
        if path:
            self.e_gclient.delete(0, "end")
            self.e_gclient.insert(0, path)

    def _bg(self, work, done_text) -> None:
        def run():
            try:
                msg = work() or done_text
            except Exception as exc:
                msg = f"Failed: {exc}"
            self.after(0, lambda: (self.refresh_status(msg), self._refresh_integrations(live=False)))
        threading.Thread(target=run, daemon=True).start()

    def _connect_google(self) -> None:
        self.s.google_client_secrets_path = self.e_gclient.get().strip()
        save_settings(self.s)
        self.refresh_status("Complete the Google sign-in in your browser…")
        self._bg(self.a.integrations.google.connect, "Google connected")

    def _connect_token(self, service: str) -> None:
        entry = self.e_slack if service == "slack" else self.e_clickup
        token = entry.get().strip()
        if not token:
            return
        entry.delete(0, "end")
        fn = self.a.integrations.connect_slack if service == "slack" else self.a.integrations.connect_clickup
        self._bg(lambda: f"{service.title()} connected as {fn(token)}", "")

    def _disconnect(self, service: str) -> None:
        self._bg(lambda: (self.a.integrations.disconnect(service), f"{service.title()} disconnected")[1], "")

    def _save_integration_options(self) -> None:
        self.s.trusted_email_domains = [d.strip().lower().lstrip("@") for d in self.e_domains.get().split(",") if d.strip()]
        self.s.slack_briefing_channels = [c.strip().lstrip("#") for c in self.e_brief.get().split(",") if c.strip()]
        self.s.clickup_title_format = self.e_cuformat.get().strip() or "{prefix} - {title}"
        save_settings(self.s)
        self.refresh_status("Checking connections…")
        self._refresh_integrations(live=True)

    def _refresh_integrations(self, live: bool) -> None:
        def run():
            st = self.a.integrations.status(live=live)
            keys = {"google": "Google (Gmail, Calendar, Drive)", "slack": "Slack", "clickup": "ClickUp"}

            def apply():
                for k, name in keys.items():
                    info = st[name]
                    self.int_status[k].configure(text=("● " if info["connected"] else "○ ") + info["detail"],
                                                 text_color="#4ade80" if info["connected"] else "#9aa1ad")
            self.after(0, apply)
        threading.Thread(target=run, daemon=True).start()

    # ---- memory --------------------------------------------------------------------------------
    def _memory(self, tab) -> None:
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x")
        self.mem_query = ctk.CTkEntry(top, placeholder_text="Search memories…")
        self.mem_query.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(top, text="Search", width=90, command=self.load_memory).pack(side="left")
        self.mem_list = ctk.CTkScrollableFrame(tab)
        self.mem_list.pack(fill="both", expand=True, pady=8)
        self.load_memory()

    def load_memory(self) -> None:
        for child in self.mem_list.winfo_children():
            child.destroy()
        items = self.a.memory.search(self.mem_query.get()) if self.mem_query.get().strip() else self.a.memory.all()
        if not items:
            ctk.CTkLabel(self.mem_list, text="No memories yet. Say “Roven, remember that…”").pack(pady=20)
        for m in items:
            row = ctk.CTkFrame(self.mem_list)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=m["content"], anchor="w", justify="left", wraplength=640).pack(
                side="left", fill="x", expand=True, padx=8, pady=6)
            ctk.CTkButton(row, text="Delete", width=70, fg_color="#7f1d1d",
                          command=lambda i=m["id"]: (self.a.memory.forget(i), self.load_memory())).pack(side="right", padx=6)

    # ---- settings -----------------------------------------------------------------------------
    def _settings(self, tab) -> None:
        f = ctk.CTkScrollableFrame(tab)
        f.pack(fill="both", expand=True)
        r = 0

        def row(label, widget):
            nonlocal r
            ctk.CTkLabel(f, text=label, anchor="w").grid(row=r, column=0, sticky="w", padx=8, pady=6)
            widget.grid(row=r, column=1, sticky="ew", padx=8, pady=6)
            r += 1

        f.grid_columnconfigure(1, weight=1)
        self.v_wake = ctk.StringVar(value=self.s.wake_engine)
        row("Wake engine (restart)", ctk.CTkOptionMenu(f, variable=self.v_wake, values=["openwakeword", "porcupine", "whisper_keyword"]))
        self.e_wake_model = ctk.CTkEntry(f)
        self.e_wake_model.insert(0, self.s.wake_model_path)
        row("Wake model file (restart)", self.e_wake_model)
        self.v_thr = ctk.DoubleVar(value=self.s.wake_threshold)
        row("Wake sensitivity threshold", ctk.CTkSlider(f, from_=0.2, to=0.9, variable=self.v_thr))
        try:
            devices = ["Default"] + [f"{i}: {n}" for i, n in self.a.mic.list_devices()]
        except Exception:
            devices = ["Default"]
        current = next((d for d in devices if d.startswith(f"{self.s.mic_device}:")), "Default")
        self.v_mic = ctk.StringVar(value=current)
        row("Microphone (restart)", ctk.CTkOptionMenu(f, variable=self.v_mic, values=devices))
        self.v_stt = ctk.StringVar(value=self.s.stt_model)
        row("Speech model (restart)", ctk.CTkOptionMenu(f, variable=self.v_stt, values=["base", "small", "medium", "large-v3"]))
        self.v_provider = ctk.StringVar(value=self.s.llm_provider)
        row("AI provider (restart)", ctk.CTkOptionMenu(f, variable=self.v_provider, values=["gemini", "anthropic"]))
        self.e_llm = ctk.CTkEntry(f)
        self.e_llm.insert(0, self.s.gemini_model if self.s.llm_provider == "gemini" else self.s.llm_model)
        row("AI model (gemini: 'auto' recommended)", self.e_llm)
        self.v_lang = ctk.StringVar(value=self.s.response_language)
        row("Response language", ctk.CTkOptionMenu(f, variable=self.v_lang,
            values=["auto", "en", "ur", "ur-Latn", "hi", "pa", "ar", "es", "fr", "de", "zh", "ja"]))
        self.v_tts = ctk.StringVar(value=self.s.tts_engine)
        row("Voice engine", ctk.CTkOptionMenu(f, variable=self.v_tts, values=["edge", "sapi"]))
        self.v_log = ctk.BooleanVar(value=self.s.daily_log_enabled)
        row("Save daily conversation log", ctk.CTkSwitch(f, text=str(self.a.chat_log.today_path()), variable=self.v_log))
        self.v_priv = ctk.BooleanVar(value=self.s.privacy_mode)
        row("Privacy mode (mic off)", ctk.CTkSwitch(f, text="", variable=self.v_priv))
        ctk.CTkLabel(f, text="Trusted medium-risk actions (run without asking):", anchor="w").grid(
            row=r, column=0, columnspan=2, sticky="w", padx=8, pady=(14, 4))
        r += 1
        self.trust_vars = {}
        for name in self.a.registry.trustable_medium_tools():
            v = ctk.BooleanVar(value=name in self.s.trusted_actions)
            self.trust_vars[name] = v
            ctk.CTkCheckBox(f, text=name, variable=v).grid(row=r, column=0, columnspan=2, sticky="w", padx=24, pady=2)
            r += 1
        self.e_key = ctk.CTkEntry(f, show="•", placeholder_text="Leave blank to keep the current key")
        row("API key for the selected provider", self.e_key)
        ctk.CTkButton(f, text="Save settings", command=self.save).grid(row=r, column=1, sticky="e", padx=8, pady=14)

    def save(self) -> None:
        s = self.s
        s.wake_engine = self.v_wake.get()
        s.wake_model_path = self.e_wake_model.get().strip()
        s.wake_threshold = round(self.v_thr.get(), 2)
        s.mic_device = None if self.v_mic.get() == "Default" else int(self.v_mic.get().split(":")[0])
        s.stt_model = self.v_stt.get()
        s.llm_provider = self.v_provider.get()
        if s.llm_provider == "gemini":
            s.gemini_model = self.e_llm.get().strip() or "auto"
        else:
            s.llm_model = self.e_llm.get().strip() or s.llm_model
        s.response_language = self.v_lang.get()
        s.tts_engine = self.v_tts.get()
        s.trusted_actions = [n for n, v in self.trust_vars.items() if v.get()]
        s.daily_log_enabled = self.v_log.get()
        self.a.set_privacy(self.v_priv.get())
        if self.e_key.get().strip():
            set_secret("gemini_api_key" if s.llm_provider == "gemini" else "anthropic_api_key", self.e_key.get().strip())
            self.e_key.delete(0, "end")
        save_settings(s)
        self.a.audit.record("settings_saved")
        self.refresh_status("Saved — items marked (restart) apply after restarting ROVEN")
