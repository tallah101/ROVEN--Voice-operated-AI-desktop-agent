"""Multi-source data collectors for the big workflows. They gather facts in one call and label where each
fact came from; the AI then reasons over them. Disconnected services are reported, never guessed."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from integrations.base import NotConnected
from integrations.clickup import link_messages_to_tasks, project_metrics

STOPWORDS = set("""a an the and or of to in on for with re fwd fw is are be was were will this that from by at as it
its we our your you i me my meeting call sync update weekly daily re: about regarding""".split())


def keywords(text: str, n: int = 4) -> list[str]:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text or "") if w.lower() not in STOPWORDS]
    seen, out = set(), []
    for w in sorted(words, key=lambda w: (-int(w[0].isupper()), -len(w))):
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out[:n]


def _section(fn):
    try:
        return fn()
    except NotConnected as exc:
        return {"not_connected": str(exc)}
    except Exception as exc:
        return {"error": str(exc)}


class Workflows:
    def __init__(self, integrations, settings) -> None:
        self.i = integrations
        self.settings = settings

    def daily_briefing(self) -> dict:
        i = self.i
        today = datetime.now()
        end_tomorrow = int((today.replace(hour=23, minute=59) + timedelta(days=1)).timestamp() * 1000)

        def calendar():
            return i.calendar.upcoming(days=1)["events"]

        def email():
            return i.gmail.search("in:inbox is:unread newer_than:1d -category:promotions -category:social", 20)

        def slack():
            chans = self.settings.slack_briefing_channels
            if not chans:
                return {"note": "No briefing channels configured (Dashboard → Integrations)."}
            return {c: _section(lambda c=c: i.slack.read_channel(c, "today", limit=80, include_threads=True)) for c in chans}

        def clickup():
            me = i.clickup.user()["id"]
            mine = i.clickup.search_tasks(assignee_ids=[me])
            now_ms = int(time.time() * 1000)
            due_soon = [t for t in mine if t["due_ms"] and t["due_ms"] <= end_tomorrow]
            return {"my_open_tasks": len(mine),
                    "overdue": [t for t in due_soon if t["due_ms"] < now_ms],
                    "due_today_or_tomorrow": [t for t in due_soon if t["due_ms"] >= now_ms],
                    "metrics": project_metrics(mine, now_ms, self.settings.stale_task_days)}

        return {"date": today.strftime("%A %d %B %Y"), "calendar": _section(calendar), "email": _section(email),
                "slack": _section(slack), "clickup": _section(clickup),
                "instructions": "Prioritise deadlines, blockers, client requests and anything addressed to the user."}

    def meeting_prep(self, query: str | None = None) -> dict:
        i = self.i
        event = i.calendar.next_meeting(query)
        if not event:
            return {"meeting": None, "note": "No upcoming meeting found in the next 7 days."}
        words = keywords(event["title"] + " " + event["description"][:200])
        emails = [a["email"] for a in event["attendees"] if a["email"]]
        out = {"meeting": event, "keywords": words}
        if emails:
            q = "(" + " OR ".join(f"from:{e} OR to:{e}" for e in emails[:8]) + ") newer_than:30d"
            out["related_email"] = _section(lambda: i.gmail.search(q, 10))
        if words:
            out["related_slack"] = _section(lambda: i.slack.search(" ".join(words[:2]) + " after:" +
                                                                   (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"), 20))
            out["related_drive"] = _section(lambda: i.drive.search(words[0], 5))

            def tasks():
                lists = i.clickup.find_lists(words[0])
                if not lists:
                    return {"note": f"No ClickUp project matches '{words[0]}'."}
                ts = i.clickup.search_tasks(list_ids=[l["id"] for l in lists])
                return project_metrics(ts, stale_days=self.settings.stale_task_days)
            out["related_clickup"] = _section(tasks)
        return out

    def project_status(self, project: str, since: str = "today") -> dict:
        i = self.i
        out: dict = {"project": project, "sources": {
            "clickup": "system of record (verified status)",
            "slack": "conversation (reported, not verified unless ClickUp agrees)"}}
        tasks: list[dict] = []

        def clickup():
            nonlocal tasks
            lists, tasks = i.clickup.project_tasks(project)
            return {"lists": [l["path"] for l in lists],
                    "metrics": project_metrics(tasks, stale_days=self.settings.stale_task_days)}
        out["clickup"] = _section(clickup)

        def slack():
            chans = i.slack.list_channels(project)
            if not chans:
                return {"note": f"No Slack channel resembles '{project}'."}
            data = i.slack.read_channel(chans[0]["name"], since, limit=150)
            msgs = data["messages"] + [r for m in data["messages"] for r in m.get("replies", [])]
            data["linked_to_clickup_tasks"] = link_messages_to_tasks(msgs, tasks)
            return data
        out["slack"] = _section(slack)
        return out

    def email_slack_crosscheck(self, message_id: str | None = None, query: str | None = None) -> dict:
        i = self.i
        if not message_id:
            found = i.gmail.search(query or "in:inbox", 1)["messages"]
            if not found:
                return {"note": "No matching email."}
            message_id = found[0]["id"]
        mail = i.gmail.read(message_id)
        words = keywords(mail["subject"] + " " + mail["body"][:300])
        after = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        return {"email": mail, "keywords": words,
                "slack": _section(lambda: i.slack.search(" ".join(words[:3]) + f" after:{after}", 25))}
