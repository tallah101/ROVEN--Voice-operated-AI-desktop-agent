"""Google Calendar (read-only): upcoming events and the next meeting."""
from __future__ import annotations

from datetime import datetime, timedelta

from integrations.base import RestClient


def normalize_event(e: dict) -> dict:
    start, end = e.get("start", {}), e.get("end", {})
    return {
        "id": e.get("id"), "title": e.get("summary", "(no title)"),
        "start": start.get("dateTime") or start.get("date"), "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start and "dateTime" not in start,
        "location": e.get("location"), "meet_link": e.get("hangoutLink"),
        "organizer": (e.get("organizer") or {}).get("email"),
        "attendees": [{"email": a.get("email"), "name": a.get("displayName"), "response": a.get("responseStatus")}
                      for a in e.get("attendees", []) if not a.get("resource")],
        "description": (e.get("description") or "")[:1500],
    }


class GoogleCalendar:
    def __init__(self, auth, http: RestClient | None = None) -> None:
        self.http = http or RestClient("Google Calendar", "https://www.googleapis.com/calendar/v3/", auth.session)

    def events(self, start: datetime, end: datetime, query: str | None = None, max_results: int = 25) -> list[dict]:
        params = {"timeMin": start.astimezone().isoformat(), "timeMax": end.astimezone().isoformat(),
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": max_results}
        if query:
            params["q"] = query
        data = self.http.request("GET", "calendars/primary/events", params=params)
        return [normalize_event(e) for e in data.get("items", []) if e.get("status") != "cancelled"]

    def upcoming(self, days: float = 1, date: str | None = None, query: str | None = None) -> dict:
        if date:
            start = datetime.fromisoformat(date)
            end = start + timedelta(days=1)
        else:
            start = datetime.now()
            end = start + timedelta(days=days)
        return {"from": start.isoformat(timespec="minutes"), "to": end.isoformat(timespec="minutes"),
                "events": self.events(start, end, query)}

    def next_meeting(self, query: str | None = None, within_days: int = 7) -> dict | None:
        now = datetime.now()
        events = [e for e in self.events(now, now + timedelta(days=within_days), query, 50) if not e["all_day"]]
        with_people = [e for e in events if e["attendees"] or e["meet_link"]]
        return (with_people or events or [None])[0]
