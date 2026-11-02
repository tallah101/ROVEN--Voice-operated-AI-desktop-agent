"""User-approved long-term memory: searchable, editable, deletable. Never stores credentials."""
from __future__ import annotations

from datetime import datetime

from security.audit_log import looks_secret


class MemoryStore:
    def __init__(self, db) -> None:
        self.db = db

    def remember(self, content: str, kind: str = "fact") -> int:
        content = content.strip()
        if not content:
            raise ValueError("Nothing to remember.")
        if looks_secret(content):
            raise ValueError("That looks like a password or key. ROVEN never stores credentials in memory.")
        existing = self.db.query("SELECT id FROM memory WHERE content = ?", (content,))
        if existing:
            return existing[0]["id"]
        now = datetime.now().isoformat(timespec="seconds")
        cur = self.db.execute(
            "INSERT INTO memory (kind, content, created, updated) VALUES (?,?,?,?)", (kind, content, now, now))
        return int(cur.lastrowid)

    def update(self, memory_id: int, content: str) -> bool:
        if looks_secret(content):
            raise ValueError("That looks like a credential; not stored.")
        now = datetime.now().isoformat(timespec="seconds")
        cur = self.db.execute("UPDATE memory SET content=?, updated=? WHERE id=?", (content.strip(), now, memory_id))
        return cur.rowcount > 0

    def forget(self, memory_id: int) -> bool:
        return self.db.execute("DELETE FROM memory WHERE id=?", (memory_id,)).rowcount > 0

    def search(self, query: str, limit: int = 20) -> list[dict]:
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return self.all(limit)
        where = " AND ".join("LOWER(content) LIKE ?" for _ in terms)
        params = tuple(f"%{t}%" for t in terms) + (limit,)
        return self.db.query(f"SELECT * FROM memory WHERE {where} ORDER BY updated DESC LIMIT ?", params)

    def all(self, limit: int = 200) -> list[dict]:
        return self.db.query("SELECT * FROM memory ORDER BY updated DESC LIMIT ?", (limit,))
