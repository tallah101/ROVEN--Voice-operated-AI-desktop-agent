"""Gmail via the official REST API: search, read, threads, contacts, drafts, replies, forwards, send, organize.
Sending only ever happens through send_draft, so every outgoing email can be reviewed first."""
from __future__ import annotations

import base64
import mimetypes
import re
from email.message import EmailMessage
from email.utils import getaddresses
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from integrations.base import RestClient

EMAIL_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
MAX_ATTACH_BYTES = 20 * 1024 * 1024


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = unescape("".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _headers(payload: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _walk_parts(payload: dict):
    yield payload
    for part in payload.get("parts", []) or []:
        yield from _walk_parts(part)


def parse_message(msg: dict, max_body: int = 8000) -> dict:
    payload = msg.get("payload", {})
    h = _headers(payload)
    plain, html, attachments = [], [], []
    for part in _walk_parts(payload):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        if part.get("filename"):
            attachments.append({"filename": part["filename"], "mime_type": mime, "size": body.get("size", 0),
                                "attachment_id": body.get("attachmentId")})
            continue
        if "data" not in body:
            continue
        text = _b64decode(body["data"]).decode("utf-8", errors="replace")
        if mime == "text/plain":
            plain.append(text)
        elif mime == "text/html":
            html.append(text)
    body_text = "\n".join(plain).strip() or html_to_text("\n".join(html))
    labels = msg.get("labelIds", [])
    return {
        "id": msg.get("id"), "thread_id": msg.get("threadId"),
        "from": h.get("from", ""), "to": h.get("to", ""), "cc": h.get("cc", ""),
        "subject": h.get("subject", "(no subject)"), "date": h.get("date", ""),
        "unread": "UNREAD" in labels, "important": "IMPORTANT" in labels, "labels": labels,
        "snippet": unescape(msg.get("snippet", "")),
        "body": body_text[:max_body], "body_truncated": len(body_text) > max_body,
        "attachments": [{k: v for k, v in a.items() if k != "attachment_id"} for a in attachments],
        "_attachments": attachments,
        "message_id_header": h.get("message-id", ""), "references": h.get("references", ""),
        "in_reply_to": h.get("in-reply-to", ""),
    }


def build_mime(to: list[str], subject: str, body: str, cc: list[str] | None = None, bcc: list[str] | None = None,
               attachments: list[tuple[str, bytes, str]] | None = None, in_reply_to: str = "",
               references: str = "") -> str:
    for addr in [*to, *(cc or []), *(bcc or [])]:
        if not EMAIL_RE.match(addr):
            raise ValueError(f"'{addr}' is not a complete email address. Resolve the recipient first.")
    if not to:
        raise ValueError("At least one recipient is required.")
    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip()
    msg.set_content(body)
    for filename, data, mime in attachments or []:
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def recipients_of(parsed: dict) -> list[str]:
    pairs = getaddresses([parsed.get("to", ""), parsed.get("cc", "")])
    return [addr.lower() for _, addr in pairs if addr]


class Gmail:
    def __init__(self, auth, http: RestClient | None = None) -> None:
        self.auth = auth
        self.http = http or RestClient("Gmail", "https://gmail.googleapis.com/gmail/v1/users/me/", auth.session)

    # ---- reading ---------------------------------------------------------------------------------
    def profile(self) -> dict:
        return self.http.request("GET", "profile")

    def _metadata(self, mid: str) -> dict:
        msg = self.http.request("GET", f"messages/{mid}",
                                params={"format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Subject", "Date"]})
        p = parse_message(msg)
        return {k: p[k] for k in ("id", "thread_id", "from", "to", "subject", "date", "unread", "important", "snippet")}

    def search(self, query: str = "", max_results: int = 10) -> dict:
        q = query.strip() or "in:inbox"
        data = self.http.request("GET", "messages", params={"q": q, "maxResults": max_results})
        ids = [m["id"] for m in data.get("messages", [])]
        return {"query": q, "count": len(ids), "messages": [self._metadata(i) for i in ids]}

    def read(self, message_id: str) -> dict:
        p = parse_message(self.http.request("GET", f"messages/{message_id}", params={"format": "full"}))
        p.pop("_attachments", None)
        return p

    def read_thread(self, thread_id: str) -> dict:
        data = self.http.request("GET", f"threads/{thread_id}", params={"format": "full"})
        msgs = []
        for m in data.get("messages", []):
            p = parse_message(m, max_body=3000)
            msgs.append({k: p[k] for k in ("id", "from", "to", "date", "subject", "body", "attachments")})
        return {"thread_id": thread_id, "message_count": len(msgs), "messages": msgs}

    def find_contact(self, name: str, limit: int = 30) -> dict:
        data = self.http.request("GET", "messages", params={"q": name, "maxResults": limit})
        tokens = [t for t in re.findall(r"\w+", name.lower()) if len(t) > 1]
        counts: dict[str, dict] = {}
        for m in data.get("messages", []):
            meta = self._metadata(m["id"])
            for display, addr in getaddresses([meta["from"], meta["to"]]):
                hay = f"{display} {addr}".lower()
                if addr and tokens and all(t in hay for t in tokens):
                    entry = counts.setdefault(addr.lower(), {"name": display, "email": addr.lower(), "messages": 0})
                    entry["messages"] += 1
        candidates = sorted(counts.values(), key=lambda c: c["messages"], reverse=True)
        return {"query": name, "candidates": candidates[:8],
                "note": "Use an address only if exactly one candidate clearly fits; otherwise ask the user."}

    # ---- drafting --------------------------------------------------------------------------------
    @staticmethod
    def _load_attachments(paths: list[str]) -> list[tuple[str, bytes, str]]:
        from security.action_validator import safe_user_path
        out, total = [], 0
        for raw in paths or []:
            p = safe_user_path(raw)
            data = p.read_bytes()
            total += len(data)
            if total > MAX_ATTACH_BYTES:
                raise ValueError("Attachments exceed Gmail's 20 MB limit for this tool.")
            out.append((p.name, data, mimetypes.guess_type(p.name)[0] or "application/octet-stream"))
        return out

    def create_draft(self, to: list[str], subject: str = "", body: str = "", cc: list[str] | None = None,
                     bcc: list[str] | None = None, attachments: list[str] | None = None,
                     reply_to_message_id: str | None = None) -> dict:
        thread_id, in_reply_to, references = None, "", ""
        if reply_to_message_id:
            orig = self.read(reply_to_message_id)
            thread_id = orig["thread_id"]
            in_reply_to, references = orig["message_id_header"], orig["references"]
            if not subject:
                subject = orig["subject"] if orig["subject"].lower().startswith("re:") else "Re: " + orig["subject"]
        raw = build_mime(to, subject, body, cc, bcc, self._load_attachments(attachments or []), in_reply_to, references)
        message = {"raw": raw, **({"threadId": thread_id} if thread_id else {})}
        draft = self.http.request("POST", "drafts", json={"message": message})
        return {"draft_id": draft["id"], "to": to, "cc": cc or [], "subject": subject,
                "status": "Draft saved in Gmail; not sent."}

    def get_draft(self, draft_id: str) -> dict:
        d = self.http.request("GET", f"drafts/{draft_id}", params={"format": "full"})
        p = parse_message(d["message"])
        p.pop("_attachments", None)
        p["draft_id"] = draft_id
        return p

    def update_draft(self, draft_id: str, to: list[str] | None = None, subject: str | None = None,
                     body: str | None = None, cc: list[str] | None = None, bcc: list[str] | None = None,
                     attachments: list[str] | None = None) -> dict:
        cur = self.get_draft(draft_id)
        to = to if to is not None else recipients_of({"to": cur["to"]})
        cc = cc if cc is not None else recipients_of({"to": cur["cc"]})
        raw = build_mime(to, subject if subject is not None else cur["subject"],
                         body if body is not None else cur["body"], cc, bcc,
                         self._load_attachments(attachments or []), cur["in_reply_to"], cur["references"])
        msg = {"raw": raw, **({"threadId": cur["thread_id"]} if cur.get("thread_id") else {})}
        self.http.request("PUT", f"drafts/{draft_id}", json={"id": draft_id, "message": msg})
        return {"draft_id": draft_id, "status": "Draft updated; not sent.",
                "note": "Attachments not re-listed in this update were dropped." if cur["attachments"] and not attachments else ""}

    def forward_draft(self, message_id: str, to: list[str], note: str = "") -> dict:
        full = parse_message(self.http.request("GET", f"messages/{message_id}", params={"format": "full"}), max_body=50000)
        files, total = [], 0
        for a in full["_attachments"]:
            if not a.get("attachment_id"):
                continue
            total += a.get("size", 0)
            if total > MAX_ATTACH_BYTES:
                break
            data = self.http.request("GET", f"messages/{message_id}/attachments/{a['attachment_id']}")
            files.append((a["filename"], _b64decode(data["data"]), a["mime_type"]))
        body = (f"{note}\n\n---------- Forwarded message ---------\nFrom: {full['from']}\nDate: {full['date']}\n"
                f"Subject: {full['subject']}\nTo: {full['to']}\n\n{full['body']}")
        subject = full["subject"] if full["subject"].lower().startswith("fwd:") else "Fwd: " + full["subject"]
        raw = build_mime(to, subject, body, attachments=files)
        draft = self.http.request("POST", "drafts", json={"message": {"raw": raw}})
        return {"draft_id": draft["id"], "to": to, "subject": subject, "attachments_forwarded": len(files),
                "status": "Forward saved as a draft; not sent."}

    def send_draft(self, draft_id: str) -> dict:
        sent = self.http.request("POST", "drafts/send", json={"id": draft_id})
        mid = sent.get("id")
        check = self.http.request("GET", f"messages/{mid}", params={"format": "minimal"}) if mid else {}
        return {"sent": "SENT" in check.get("labelIds", []), "message_id": mid, "thread_id": sent.get("threadId")}

    # ---- organizing ------------------------------------------------------------------------------
    ACTIONS = {
        "archive": ([], ["INBOX"]), "mark_read": ([], ["UNREAD"]), "mark_unread": (["UNREAD"], []),
        "star": (["STARRED"], []), "unstar": ([], ["STARRED"]), "move_to_inbox": (["INBOX"], []),
    }

    def modify(self, message_ids: list[str], action: str) -> dict:
        add, remove = self.ACTIONS[action]
        self.http.request("POST", "messages/batchModify",
                          json={"ids": message_ids, "addLabelIds": add, "removeLabelIds": remove})
        return {"action": action, "messages": len(message_ids)}
