"""Spoken reminders ('remind me at 5 to call Ahmed')."""
from __future__ import annotations

from datetime import datetime

SCHEMA = """CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, due TEXT NOT NULL, message TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)"""


class Reminders:
    def __init__(self, db) -> None:
        self.db = db
        db.execute(SCHEMA)

    def add(self, when: str, message: str) -> dict:
        due = datetime.fromisoformat(when.replace(" ", "T"))
        if due < datetime.now():
            raise ValueError("That time has already passed.")
        rid = self.db.execute("INSERT INTO reminders (due, message) VALUES (?, ?)",
                              (due.isoformat(timespec="minutes"), message)).lastrowid
        return {"reminder_id": rid, "due": due.strftime("%A %d %B, %H:%M"), "message": message}

    def pending(self) -> list[dict]:
        return self.db.query("SELECT * FROM reminders WHERE done=0 ORDER BY due")

    def due_now(self, now: datetime | None = None) -> list[dict]:
        now = (now or datetime.now()).isoformat(timespec="minutes")
        return self.db.query("SELECT * FROM reminders WHERE done=0 AND due <= ? ORDER BY due", (now,))

    def mark_done(self, rid: int) -> None:
        self.db.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))

    def cancel(self, rid: int) -> dict:
        return {"cancelled": self.db.execute("UPDATE reminders SET done=1 WHERE id=? AND done=0", (rid,)).rowcount > 0}
