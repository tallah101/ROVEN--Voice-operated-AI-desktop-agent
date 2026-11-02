"""Persists every request and its tool steps so an interrupted task (crash, power loss, emergency stop)
can be resumed without repeating steps that already had side effects."""
from __future__ import annotations

import json
from datetime import datetime, timedelta


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class WorkflowStore:
    def __init__(self, db) -> None:
        self.db = db

    def mark_interrupted_on_startup(self) -> int:
        return self.db.execute("UPDATE workflows SET status='interrupted' WHERE status='running'").rowcount

    def begin(self, request: str) -> int:
        cur = self.db.execute("INSERT INTO workflows (request, started, status) VALUES (?,?, 'running')",
                              (request, _now()))
        return int(cur.lastrowid)

    def add_step(self, wid: int, tool: str, args: dict, ok: bool, result: str) -> None:
        row = self.db.query("SELECT steps FROM workflows WHERE id=?", (wid,))
        if not row:
            return
        steps = json.loads(row[0]["steps"])
        steps.append({"tool": tool, "args": args, "ok": ok, "result": result[:300], "at": _now()})
        self.db.execute("UPDATE workflows SET steps=? WHERE id=?",
                        (json.dumps(steps[-60:], ensure_ascii=False, default=str), wid))

    def finish(self, wid: int, status: str) -> None:
        self.db.execute("UPDATE workflows SET status=?, finished=? WHERE id=?", (status, _now(), wid))

    def get(self, wid: int) -> dict | None:
        rows = self.db.query("SELECT * FROM workflows WHERE id=?", (wid,))
        if not rows:
            return None
        row = rows[0]
        row["steps"] = json.loads(row["steps"])
        return row

    def pending_interrupted(self, max_age_hours: float = 24) -> dict | None:
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
        rows = self.db.query("SELECT id FROM workflows WHERE status IN ('interrupted','cancelled') AND acknowledged=0 "
                             "AND started > ? ORDER BY id DESC LIMIT 1", (cutoff,))
        return self.get(rows[0]["id"]) if rows else None

    def latest_interrupted(self) -> dict | None:
        rows = self.db.query("SELECT id FROM workflows WHERE status IN ('interrupted','cancelled') ORDER BY id DESC LIMIT 1")
        return self.get(rows[0]["id"]) if rows else None

    def acknowledge(self, wid: int) -> None:
        self.db.execute("UPDATE workflows SET acknowledged=1 WHERE id=?", (wid,))

    def recent(self, limit: int = 30) -> list[dict]:
        return self.db.query("SELECT id, request, started, finished, status FROM workflows ORDER BY id DESC LIMIT ?",
                             (limit,))
