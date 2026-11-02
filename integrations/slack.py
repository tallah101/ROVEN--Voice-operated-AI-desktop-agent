"""Slack Web API with a user token (xoxp-): reads exactly what *you* can see — nothing more.
Channels you are not in, or private channels you were not invited to, are reported as inaccessible."""
from __future__ import annotations

import html
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from core.text_match import rank
from integrations.base import ApiError, NotConnected, RestClient

MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]+)?>")
CHANNEL = re.compile(r"<#(C[A-Z0-9]+)(?:\|([^>]*))?>")
LINK = re.compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>")
SPECIAL = re.compile(r"<!(here|channel|everyone)[^>]*>")
AUTH_ERRORS = {"not_authed", "invalid_auth", "token_revoked", "token_expired", "account_inactive"}


def format_text(text: str, name_of) -> str:
    text = MENTION.sub(lambda m: "@" + name_of(m.group(1)), text or "")
    text = CHANNEL.sub(lambda m: "#" + (m.group(2) or m.group(1)), text)
    text = LINK.sub(lambda m: f"{m.group(2)} ({m.group(1)})" if m.group(2) else m.group(1), text)
    text = SPECIAL.sub(lambda m: "@" + m.group(1), text)
    return html.unescape(text)


def time_window(since: str, now: datetime | None = None) -> tuple[float, float | None]:
    """'today' | 'yesterday' | 'this_week' | '6h' | '3d' | 'YYYY-MM-DD' -> (oldest, latest) epoch seconds."""
    now = now or datetime.now()
    s = (since or "today").strip().lower()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if s == "today":
        return midnight.timestamp(), None
    if s == "yesterday":
        return (midnight - timedelta(days=1)).timestamp(), midnight.timestamp()
    if s == "this_week":
        return (midnight - timedelta(days=now.weekday())).timestamp(), None
    m = re.fullmatch(r"(\d+)\s*(h|hours?|d|days?)", s)
    if m:
        n = int(m.group(1))
        delta = timedelta(hours=n) if m.group(2).startswith("h") else timedelta(days=n)
        return (now - delta).timestamp(), None
    try:
        day = datetime.fromisoformat(s)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), (start + timedelta(days=1)).timestamp()
    except ValueError:
        raise ValueError("since must be today, yesterday, this_week, '<n>h', '<n>d' or YYYY-MM-DD")


def _clock(ts: str) -> str:
    return datetime.fromtimestamp(float(ts)).strftime("%a %d %b %H:%M")


class Slack:
    def __init__(self, token_getter, http: RestClient | None = None) -> None:
        self._token_getter = token_getter
        self._session = None
        self._session_token = None
        self.http = http or RestClient("Slack", "https://slack.com/api/", self._make_session)
        self._users: dict[str, str] = {}
        self._channels: list[dict] | None = None
        self._channels_at = 0.0
        self._me: dict | None = None
        self._lock = threading.Lock()

    def connected(self) -> bool:
        try:
            return bool(self._token_getter())
        except Exception:
            return False

    def _make_session(self):
        token = self._token_getter()
        if not token:
            raise NotConnected("Slack is not connected. Add your Slack user token in Dashboard → Integrations.")
        if self._session is None or token != self._session_token:
            s = requests.Session()
            s.headers["Authorization"] = f"Bearer {token}"
            self._session, self._session_token = s, token
        return self._session

    def call(self, method: str, http_method: str = "GET", **params) -> dict:
        if http_method == "GET":
            data = self.http.request("GET", method, params=params)
        else:
            data = self.http.request("POST", method, json=params)
        if not data.get("ok"):
            err = data.get("error", "unknown_error")
            if err in AUTH_ERRORS:
                raise NotConnected("Slack rejected the token. Update it in Dashboard → Integrations.")
            if err == "missing_scope":
                raise ApiError("Slack", 403, f"the token lacks permission '{data.get('needed')}' (see README → Slack scopes)")
            if err in ("channel_not_found", "not_in_channel"):
                raise ApiError("Slack", 404, "that channel isn't accessible with your account (not a member, or private)")
            raise ApiError("Slack", 200, err)
        return data

    def _paginate(self, method: str, key: str, max_pages: int = 10, **params) -> list:
        out, cursor = [], None
        for _ in range(max_pages):
            if cursor:
                params["cursor"] = cursor
            data = self.call(method, **params)
            out.extend(data.get(key, []))
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
        return out

    # ---- identity, users, channels -----------------------------------------------------------
    def me(self) -> dict:
        if self._me is None:
            d = self.call("auth.test")
            self._me = {"user_id": d["user_id"], "user": d["user"], "team": d.get("team"), "url": d.get("url")}
        return self._me

    def user_name(self, uid: str) -> str:
        if uid not in self._users:
            try:
                u = self.call("users.info", user=uid)["user"]
                p = u.get("profile", {})
                self._users[uid] = p.get("display_name") or p.get("real_name") or u.get("name") or uid
            except Exception:
                self._users[uid] = uid
        return self._users[uid]

    def find_user(self, name: str) -> dict:
        members = self._paginate("users.list", "members", limit=500)
        live = [m for m in members if not m.get("deleted") and not m.get("is_bot")]
        labels = [f"{m.get('profile', {}).get('real_name', '')} {m.get('profile', {}).get('display_name', '')} {m.get('name', '')}"
                  for m in live]
        hits = rank(name, labels, min_score=0.45, limit=5)
        for m in live:
            self._users[m["id"]] = m.get("profile", {}).get("display_name") or m.get("profile", {}).get("real_name") or m["name"]
        return {"query": name, "candidates": [
            {"id": live[i]["id"], "name": live[i].get("profile", {}).get("real_name"),
             "display_name": live[i].get("profile", {}).get("display_name"), "title": live[i].get("profile", {}).get("title")}
            for i, _ in hits]}

    def channels(self, refresh: bool = False) -> list[dict]:
        with self._lock:
            if refresh or self._channels is None or time.time() - self._channels_at > 600:
                raw = self._paginate("conversations.list", "channels", limit=1000, exclude_archived="true",
                                     types="public_channel,private_channel")
                self._channels = [{"id": c["id"], "name": c["name"], "private": c.get("is_private", False),
                                   "member": c.get("is_member", False),
                                   "shared_external": c.get("is_ext_shared", False) or c.get("is_shared", False),
                                   "topic": (c.get("topic") or {}).get("value", "")[:120]} for c in raw]
                self._channels_at = time.time()
            return self._channels

    def list_channels(self, filter: str = "") -> list[dict]:
        chans = self.channels()
        if filter:
            names = [c["name"] for c in chans]
            return [chans[i] for i, _ in rank(filter, names, min_score=0.4, limit=15)]
        return [c for c in chans if c["member"]][:100]

    def resolve_channel(self, name_or_id: str) -> dict:
        q = name_or_id.strip().lstrip("#")
        chans = self.channels()
        for c in chans:
            if c["id"] == q or c["name"].lower() == q.lower():
                return c
        hits = rank(q, [c["name"] for c in chans], min_score=0.6, limit=2)
        if not hits:
            raise LookupError(f"No accessible Slack channel matches '{name_or_id}'.")
        return chans[hits[0][0]]

    def _dm_channel(self, user_query: str) -> tuple[str, str]:
        cands = self.find_user(user_query.lstrip("@"))["candidates"]
        if len(cands) != 1:
            raise LookupError(f"'{user_query}' matches {len(cands)} Slack users; ask which one: "
                              + ", ".join(c['name'] or c['display_name'] or c['id'] for c in cands))
        ch = self.call("conversations.open", "POST", users=cands[0]["id"])["channel"]["id"]
        return ch, cands[0]["name"] or cands[0]["id"]

    # ---- reading ---------------------------------------------------------------------------------
    def _format_msg(self, m: dict) -> dict:
        out = {"ts": m["ts"], "time": _clock(m["ts"]),
               "user": self.user_name(m["user"]) if m.get("user") else (m.get("username") or m.get("bot_id") or "app"),
               "text": format_text(m.get("text", ""), self.user_name)}
        if m.get("reply_count"):
            out["thread_replies"] = m["reply_count"]
        if m.get("files"):
            out["files"] = [f.get("name") for f in m["files"]]
        return out

    def read_channel(self, channel: str, since: str = "today", limit: int = 100, include_threads: bool = True) -> dict:
        c = self.resolve_channel(channel)
        oldest, latest = time_window(since)
        params = {"channel": c["id"], "oldest": f"{oldest:.6f}", "limit": min(limit, 200)}
        if latest:
            params["latest"] = f"{latest:.6f}"
        raw = self._paginate("conversations.history", "messages", max_pages=max(1, limit // 200 + 1), **params)[:limit]
        raw.reverse()
        messages = [self._format_msg(m) for m in raw if m.get("subtype") not in ("channel_join", "channel_leave")]
        threads_read = 0
        if include_threads:
            for msg in messages:
                if msg.get("thread_replies") and threads_read < 8:
                    msg["replies"] = self.read_thread(c["id"], msg["ts"], limit=30)["replies"]
                    threads_read += 1
        return {"channel": "#" + c["name"], "since": since, "message_count": len(messages), "messages": messages,
                "truncated": len(raw) >= limit}

    def read_thread(self, channel: str, thread_ts: str, limit: int = 100) -> dict:
        cid = channel if re.fullmatch(r"[CDG][A-Z0-9]+", channel) else self.resolve_channel(channel)["id"]
        msgs = self._paginate("conversations.replies", "messages", max_pages=3, channel=cid, ts=thread_ts, limit=min(limit, 200))
        formatted = [self._format_msg(m) for m in msgs]
        return {"parent": formatted[0] if formatted else None, "replies": formatted[1:limit]}

    def search(self, query: str, count: int = 20) -> dict:
        d = self.call("search.messages", query=query, count=min(count, 100), sort="timestamp", sort_dir="desc")
        matches = d.get("messages", {}).get("matches", [])
        return {"query": query, "total": d.get("messages", {}).get("total", 0), "results": [
            {"channel": "#" + (m.get("channel") or {}).get("name", "?"), "user": m.get("username") or self.user_name(m.get("user", "")),
             "time": _clock(m["ts"]), "ts": m["ts"], "text": format_text(m.get("text", ""), self.user_name),
             "permalink": m.get("permalink")} for m in matches]}

    # ---- writing ---------------------------------------------------------------------------------
    def target_info(self, target: str) -> dict:
        if target.strip().startswith("@"):
            return {"kind": "dm", "name": target, "external": False}
        c = self.resolve_channel(target)
        return {"kind": "channel", "name": "#" + c["name"], "external": c["shared_external"]}

    def send_message(self, target: str, text: str, thread_ts: str | None = None) -> dict:
        if target.strip().startswith("@"):
            cid, label = self._dm_channel(target)
        else:
            c = self.resolve_channel(target)
            cid, label = c["id"], "#" + c["name"]
        params = {"channel": cid, "text": text}
        if thread_ts:
            params["thread_ts"] = thread_ts
        d = self.call("chat.postMessage", "POST", **params)
        return {"posted": bool(d.get("ts")), "to": label, "ts": d.get("ts")}

    def upload_file(self, target: str, path: str, comment: str = "") -> dict:
        from security.action_validator import safe_user_path
        p = safe_user_path(path)
        data = p.read_bytes()
        cid = self._dm_channel(target)[0] if target.startswith("@") else self.resolve_channel(target)["id"]
        up = self.call("files.getUploadURLExternal", filename=p.name, length=len(data))
        r = requests.post(up["upload_url"], files={"file": (p.name, data)}, timeout=120)
        if r.status_code >= 400:
            raise ApiError("Slack", r.status_code, "file upload failed")
        d = self.call("files.completeUploadExternal", "POST", files=[{"id": up["file_id"], "title": p.name}],
                      channel_id=cid, initial_comment=comment)
        return {"uploaded": bool(d.get("files")), "file": p.name}
