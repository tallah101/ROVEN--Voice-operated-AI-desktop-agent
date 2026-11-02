"""ClickUp API v2 with a personal token (pk_...). Reports use only ClickUp's own fields —
missing estimates or tracked time are reported as gaps, never filled in."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

import requests

from core.text_match import match_score, normalize, rank
from integrations.base import NotConnected, RestClient

QA_RE = re.compile(r"\b(qa|review|in review|testing|test|verify|verification|uat)\b", re.I)
BLOCKED_RE = re.compile(r"(block|on hold|waiting|stuck)", re.I)
PROGRESS_RE = re.compile(r"(progress|doing|development|dev|working|active)", re.I)


def _ms(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _iso(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d") if ms else None


def normalize_task(t: dict) -> dict:
    status = (t.get("status") or {})
    est, spent = _ms(t.get("time_estimate")), _ms(t.get("time_spent"))
    return {
        "id": t["id"], "custom_id": t.get("custom_id"), "name": t.get("name", ""),
        "status": status.get("status", ""), "status_type": status.get("type", ""),
        "assignees": [a.get("username") or a.get("email") or str(a.get("id")) for a in t.get("assignees", [])],
        "due": _iso(_ms(t.get("due_date"))), "due_ms": _ms(t.get("due_date")),
        "updated_ms": _ms(t.get("date_updated")), "closed_ms": _ms(t.get("date_closed") or t.get("date_done")),
        "estimate_h": round(est / 3_600_000, 2) if est else None,
        "spent_h": round(spent / 3_600_000, 2) if spent else None,
        "priority": (t.get("priority") or {}).get("priority"),
        "list": (t.get("list") or {}).get("name"), "url": t.get("url"),
        "tags": [g.get("name", "") for g in t.get("tags", [])],
        "depends_on": [d.get("depends_on") for d in t.get("dependencies", []) if d.get("task_id") == t["id"]],
        "parent": t.get("parent"),
    }


def build_task_name(prefix: str, title: str, prefixes: dict, fmt: str = "{prefix} - {title}") -> str:
    prefix = prefix.strip().upper()
    if prefix not in prefixes:
        raise ValueError(f"Unknown task category '{prefix}'. Use one of: {', '.join(prefixes)}")
    clean = re.sub(rf"^\s*{re.escape(prefix)}\s*[-:|]\s*", "", title.strip(), flags=re.I)
    return fmt.format(prefix=prefix, title=clean)


def project_metrics(tasks: list[dict], now_ms: int | None = None, stale_days: int = 5) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    week_start = datetime.fromtimestamp(now_ms / 1000).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_ms = int((week_start - timedelta(days=week_start.weekday())).timestamp() * 1000)
    stale_ms = now_ms - stale_days * 86_400_000
    by_id = {t["id"]: t for t in tasks}

    def closed(t):
        return t["status_type"] in ("closed", "done") or bool(t["closed_ms"])

    def brief(t):
        return {k: t[k] for k in ("id", "custom_id", "name", "status", "assignees", "due", "estimate_h", "spent_h", "url")}

    groups = {k: [] for k in ("completed", "qa", "blocked", "in_progress", "todo")}
    overdue, stale, over_estimate, completed_week = [], [], [], []
    workload: dict[str, dict] = {}
    for t in tasks:
        is_closed = closed(t)
        waits_on_open = any(d in by_id and not closed(by_id[d]) for d in t["depends_on"])
        if is_closed:
            groups["completed"].append(t)
            if t["closed_ms"] and t["closed_ms"] >= week_start_ms:
                completed_week.append(t)
        elif BLOCKED_RE.search(t["status"]) or any("block" in g.lower() for g in t["tags"]) or waits_on_open:
            groups["blocked"].append(t)
        elif QA_RE.search(t["status"]):
            groups["qa"].append(t)
        elif PROGRESS_RE.search(t["status"]) or (t["status_type"] == "custom"):
            groups["in_progress"].append(t)
        else:
            groups["todo"].append(t)
        if not is_closed and t["due_ms"] and t["due_ms"] < now_ms:
            overdue.append(t)
        if not is_closed and t["updated_ms"] and t["updated_ms"] < stale_ms:
            stale.append(t)
        if t["estimate_h"] and t["spent_h"] and t["spent_h"] > t["estimate_h"]:
            over_estimate.append(t)
        for person in t["assignees"] or ["(unassigned)"]:
            w = workload.setdefault(person, {"open": 0, "in_progress": 0, "overdue": 0, "open_estimate_h": 0.0,
                                             "tracked_h": 0.0, "completed": 0})
            if is_closed:
                w["completed"] += 1
            else:
                w["open"] += 1
                w["open_estimate_h"] = round(w["open_estimate_h"] + (t["estimate_h"] or 0), 2)
                if t in groups["in_progress"]:
                    w["in_progress"] += 1
                if t in overdue:
                    w["overdue"] += 1
            w["tracked_h"] = round(w["tracked_h"] + (t["spent_h"] or 0), 2)

    with_both = [t for t in tasks if t["estimate_h"] and t["spent_h"]]
    return {
        "total_tasks": len(tasks),
        "counts": {k: len(v) for k, v in groups.items()},
        "completed_this_week": [brief(t) for t in completed_week],
        "in_progress": [brief(t) for t in groups["in_progress"]],
        "waiting_for_qa": [brief(t) for t in groups["qa"]],
        "blocked": [brief(t) | {"waiting_on": t["depends_on"]} for t in groups["blocked"]],
        "todo": [brief(t) for t in groups["todo"]],
        "overdue": [brief(t) | {"days_overdue": int((now_ms - t["due_ms"]) / 86_400_000)} for t in overdue],
        "no_update_in_days": {"days": stale_days, "tasks": [brief(t) for t in stale]},
        "over_estimate": [brief(t) | {"over_by_h": round(t["spent_h"] - t["estimate_h"], 2)} for t in over_estimate],
        "estimate_vs_tracked": {
            "tasks_with_both": len(with_both),
            "estimated_h": round(sum(t["estimate_h"] for t in with_both), 2),
            "tracked_h": round(sum(t["spent_h"] for t in with_both), 2),
        },
        "workload": workload,
        "data_gaps": {
            "without_estimate": sum(1 for t in tasks if not t["estimate_h"]),
            "without_tracked_time": sum(1 for t in tasks if not t["spent_h"]),
            "without_assignee": sum(1 for t in tasks if not t["assignees"]),
            "open_without_due_date": sum(1 for t in tasks if not t["due_ms"] and not closed(t)),
        },
        "note": "All figures come from ClickUp fields. Tasks missing estimates or tracked time are excluded from "
                "time comparisons, not assumed to be zero. Status buckets follow each list's status names.",
    }


def link_messages_to_tasks(messages: list[dict], tasks: list[dict]) -> list[dict]:
    """Attach likely ClickUp task references to Slack messages (task ids, custom ids, URLs or long task names)."""
    linked = []
    for m in messages:
        text = m.get("text", "")
        low = normalize(text)
        hits = []
        for t in tasks:
            name_core = normalize(re.sub(r"^[A-Z]{2,4}\s*[-:|]\s*", "", t["name"]))
            if (t["id"] in text or (t.get("custom_id") and t["custom_id"] in text)
                    or (len(name_core) >= 12 and name_core in low)):
                hits.append(t["id"])
        if hits:
            linked.append({"ts": m.get("ts"), "user": m.get("user"), "text": text[:200], "task_ids": hits})
    return linked


class ClickUp:
    def __init__(self, token_getter, settings, http: RestClient | None = None) -> None:
        self._token_getter = token_getter
        self.settings = settings
        self._session = None
        self._session_token = None
        self.http = http or RestClient("ClickUp", "https://api.clickup.com/api/v2/", self._make_session)
        self._team: str | None = None
        self._hier: list[dict] | None = None
        self._hier_at = 0.0
        self._members: list[dict] | None = None

    def connected(self) -> bool:
        try:
            return bool(self._token_getter())
        except Exception:
            return False

    def _make_session(self):
        token = self._token_getter()
        if not token:
            raise NotConnected("ClickUp is not connected. Add your ClickUp token in Dashboard → Integrations.")
        if self._session is None or token != self._session_token:
            s = requests.Session()
            s.headers["Authorization"] = token
            self._session, self._session_token = s, token
        return self._session

    # ---- structure --------------------------------------------------------------------------------
    def user(self) -> dict:
        return self.http.request("GET", "user")["user"]

    def team_id(self) -> str:
        if self._team is None:
            if self.settings.clickup_team_id:
                self._team = str(self.settings.clickup_team_id)
            else:
                teams = self.http.request("GET", "team")["teams"]
                if not teams:
                    raise LookupError("This ClickUp token has no workspaces.")
                self._team = str(teams[0]["id"])
        return self._team

    def members(self) -> list[dict]:
        if self._members is None:
            teams = self.http.request("GET", "team")["teams"]
            team = next((t for t in teams if str(t["id"]) == self.team_id()), teams[0])
            self._members = [{"id": m["user"]["id"], "username": m["user"].get("username"), "email": m["user"].get("email")}
                             for m in team.get("members", [])]
        return self._members

    def find_member(self, name: str) -> list[dict]:
        ms = self.members()
        hits = rank(name, [f"{m['username'] or ''} {m['email'] or ''}" for m in ms], min_score=0.45, limit=5)
        return [ms[i] for i, _ in hits]

    def resolve_member_ids(self, names: list[str]) -> list[int]:
        ids = []
        for n in names:
            c = self.find_member(n)
            if len(c) == 0:
                raise LookupError(f"No ClickUp member matches '{n}'.")
            if len(c) > 1 and match_score(n, c[0]["username"] or "") < 0.95:
                raise LookupError(f"'{n}' matches several ClickUp members: {', '.join(m['username'] for m in c)}. Ask which one.")
            ids.append(c[0]["id"])
        return ids

    def hierarchy(self) -> list[dict]:
        if self._hier is None or time.time() - self._hier_at > 600:
            lists = []
            for sp in self.http.request("GET", f"team/{self.team_id()}/space", params={"archived": "false"})["spaces"]:
                for f in self.http.request("GET", f"space/{sp['id']}/folder", params={"archived": "false"})["folders"]:
                    for li in f.get("lists", []):
                        lists.append({"id": li["id"], "name": li["name"], "space": sp["name"], "folder": f["name"],
                                      "path": f"{sp['name']} / {f['name']} / {li['name']}"})
                for li in self.http.request("GET", f"space/{sp['id']}/list", params={"archived": "false"})["lists"]:
                    lists.append({"id": li["id"], "name": li["name"], "space": sp["name"], "folder": None,
                                  "path": f"{sp['name']} / {li['name']}"})
            self._hier, self._hier_at = lists, time.time()
        return self._hier

    def find_lists(self, query: str) -> list[dict]:
        """A 'project' may be a space, a folder or a list. Returns every list belonging to the best match."""
        lists = self.hierarchy()
        for level in ("space", "folder"):
            names = sorted({li[level] for li in lists if li[level]})
            hit = rank(query, names, min_score=0.75, limit=1)
            if hit:
                chosen = names[hit[0][0]]
                return [li for li in lists if li[level] == chosen]
        return [lists[i] for i, _ in rank(query, [li["path"] for li in lists], min_score=0.5, limit=8)]

    # ---- tasks ---------------------------------------------------------------------------------------
    def search_tasks(self, list_ids: list[str] | None = None, assignee_ids: list[int] | None = None,
                     statuses: list[str] | None = None, include_closed: bool = False, due_before_ms: int | None = None,
                     updated_after_ms: int | None = None, max_pages: int = 10) -> list[dict]:
        params: dict = {"include_closed": str(include_closed).lower(), "subtasks": "true", "order_by": "updated"}
        if list_ids:
            params["list_ids[]"] = list_ids
        if assignee_ids:
            params["assignees[]"] = [str(a) for a in assignee_ids]
        if statuses:
            params["statuses[]"] = statuses
        if due_before_ms:
            params["due_date_lt"] = due_before_ms
        if updated_after_ms:
            params["date_updated_gt"] = updated_after_ms
        out = []
        for page in range(max_pages):
            data = self.http.request("GET", f"team/{self.team_id()}/task", params={**params, "page": page})
            batch = data.get("tasks", [])
            out.extend(normalize_task(t) for t in batch)
            if data.get("last_page", True) or len(batch) < 100:
                break
        return out

    def project_tasks(self, project: str, recent_closed_days: int = 14) -> tuple[list[dict], list[dict]]:
        lists = self.find_lists(project)
        if not lists:
            raise LookupError(f"No ClickUp space, folder or list matches '{project}'.")
        ids = [li["id"] for li in lists]
        open_tasks = self.search_tasks(list_ids=ids)
        since = int((time.time() - recent_closed_days * 86400) * 1000)
        recent = [t for t in self.search_tasks(list_ids=ids, include_closed=True, updated_after_ms=since)
                  if t["status_type"] in ("closed", "done") or t["closed_ms"]]
        merged = {t["id"]: t for t in open_tasks + recent}
        return lists, list(merged.values())

    def get_task(self, task_id: str, comments: int = 10) -> dict:
        t = self.http.request("GET", f"task/{task_id}", params={"include_subtasks": "true"})
        out = normalize_task(t)
        out["description"] = (t.get("text_content") or t.get("description") or "")[:3000]
        out["subtasks"] = [normalize_task(s)["name"] for s in t.get("subtasks", [])]
        if comments:
            cs = self.http.request("GET", f"task/{task_id}/comment").get("comments", [])
            out["recent_comments"] = [{"user": (c.get("user") or {}).get("username"), "date": _iso(_ms(c.get("date"))),
                                       "text": c.get("comment_text", "")[:500]} for c in cs[:comments]]
        return out

    def create_task(self, list_id: str, name: str, description: str = "", assignee_ids: list[int] | None = None,
                    due_ms: int | None = None, priority: int | None = None, tags: list[str] | None = None) -> dict:
        body = {"name": name, "description": description, "assignees": assignee_ids or [], "tags": tags or []}
        if due_ms:
            body["due_date"] = due_ms
        if priority:
            body["priority"] = priority
        t = self.http.request("POST", f"list/{list_id}/task", json=body)
        return {"created": bool(t.get("id")), "task": normalize_task(t)}

    def update_task(self, task_id: str, **fields) -> dict:
        body = {k: v for k, v in fields.items() if v is not None}
        t = self.http.request("PUT", f"task/{task_id}", json=body)
        return {"updated": True, "task": normalize_task(t)}

    def add_comment(self, task_id: str, text: str) -> dict:
        c = self.http.request("POST", f"task/{task_id}/comment", json={"comment_text": text, "notify_all": False})
        return {"commented": bool(c.get("id"))}
