"""Daily plain-text conversation log: Documents\\Roven (DD-MM-YYYY).txt

Every line is written immediately (nothing is lost if the PC crashes). A new file starts automatically
after midnight. Secrets are redacted. Files are UTF-8 with a BOM so Notepad shows Urdu/Hindi correctly."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from security.audit_log import redact


class DailyConversationLog:
    def __init__(self, settings, folder_resolver: Callable[[], Path] | None = None,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.settings = settings
        self.folder_resolver = folder_resolver
        self.clock = clock
        self._lock = threading.Lock()

    def folder(self) -> Path:
        if self.settings.daily_log_folder:
            return Path(self.settings.daily_log_folder).expanduser()
        if self.folder_resolver:
            return self.folder_resolver()
        from core.paths import known_folder
        return known_folder("documents")

    def path_for(self, when: datetime) -> Path:
        name = self.settings.daily_log_name.format(date=when.strftime(self.settings.daily_log_date_format))
        return self.folder() / f"{name}.txt"

    def today_path(self) -> Path:
        return self.path_for(self.clock())

    def write(self, speaker: str, text: str) -> None:
        if not self.settings.daily_log_enabled or not text:
            return
        now = self.clock()
        path = self.path_for(now)
        body = redact(str(text)).strip().replace("\r", "")
        indent = " " * 13
        body = body.replace("\n", "\n" + indent)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            new = not path.exists()
            with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="\r\n") as f:
                if new:
                    f.write(f"ROVEN conversation log — {now.strftime('%A, %d %B %Y')}\n{'=' * 60}\n\n")
                if speaker == "---":
                    f.write(f"\n--- {body} ({now.strftime('%H:%M')}) ---\n")
                else:
                    f.write(f"[{now.strftime('%H:%M:%S')}] {speaker}: {body}\n")

    # convenience wrappers
    def session_start(self) -> None:
        self.write("---", "Conversation started")

    def user(self, text: str, language: str | None = None) -> None:
        self.write("You", text + (f"   ({language})" if language else ""))

    def roven(self, text: str) -> None:
        self.write("ROVEN", text)

    def action(self, name: str, summary: str, ok: bool, status: str) -> None:
        self.write("Action", f"{summary} — {status}")
