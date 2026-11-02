"""Activity log with secret redaction. Nothing secret should ever reach disk."""
from __future__ import annotations

import json
import re
from datetime import datetime

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bpk_[A-Za-z0-9_]{10,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_\-]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_\- ]?key)\b\s*[:=]\s*\S+"),
]


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def looks_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


class AuditLog:
    def __init__(self, db) -> None:
        self.db = db

    def record(self, event: str, tool: str | None = None, args=None,
               status: str | None = None, detail=None) -> None:
        args_s = None
        if args is not None:
            args_s = redact(json.dumps(args, ensure_ascii=False, default=str))[:4000]
        detail_s = redact(str(detail))[:4000] if detail is not None else None
        self.db.execute(
            "INSERT INTO audit_log (ts, event, tool, args, status, detail) VALUES (?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), event, tool, args_s, status, detail_s),
        )

    def recent(self, limit: int = 100) -> list[dict]:
        return self.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
