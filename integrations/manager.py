"""One place that owns every integration, its connection state and its tool group names."""
from __future__ import annotations

from integrations.base import NotConnected
from integrations.clickup import ClickUp
from integrations.gmail import Gmail
from integrations.google_auth import GoogleAuth
from integrations.google_calendar import GoogleCalendar
from integrations.google_drive import GoogleDrive
from integrations.slack import Slack
from security.credentials import delete_secret, get_secret, set_secret


def _secret(name):
    def getter():
        try:
            return get_secret(name)
        except Exception:
            return None
    return getter


class Integrations:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.google = GoogleAuth(settings)
        self.gmail = Gmail(self.google)
        self.calendar = GoogleCalendar(self.google)
        self.drive = GoogleDrive(self.google)
        self.slack = Slack(_secret("slack_user_token"))
        self.clickup = ClickUp(_secret("clickup_token"), settings)

    def connected_groups(self) -> set[str]:
        groups = set()
        if self.google.connected():
            groups |= {"gmail", "calendar", "drive"}
        if self.slack.connected():
            groups.add("slack")
        if self.clickup.connected():
            groups.add("clickup")
        return groups

    def status(self, live: bool = False) -> dict:
        out = {}
        checks = {
            "Google (Gmail, Calendar, Drive)": (self.google.connected, lambda: self.gmail.profile().get("emailAddress")),
            "Slack": (self.slack.connected, lambda: f"{self.slack.me()['user']} @ {self.slack.me()['team']}"),
            "ClickUp": (self.clickup.connected, lambda: self.clickup.user().get("username")),
        }
        for name, (is_connected, who) in checks.items():
            if not is_connected():
                out[name] = {"connected": False, "detail": "Not connected"}
                continue
            if not live:
                out[name] = {"connected": True, "detail": "Credentials saved"}
                continue
            try:
                out[name] = {"connected": True, "detail": f"Connected as {who()}"}
            except NotConnected as exc:
                out[name] = {"connected": False, "detail": str(exc)}
            except Exception as exc:
                out[name] = {"connected": True, "detail": f"Saved, but check failed: {exc}"}
        return out

    # token-based connections (validated before saving)
    def connect_slack(self, token: str) -> str:
        token = token.strip()
        if not token.startswith("xoxp-"):
            raise ValueError("Use a Slack *user* token (starts with xoxp-) so ROVEN sees exactly what you can see.")
        probe = Slack(lambda: token)
        who = probe.me()
        set_secret("slack_user_token", token)
        self.slack = Slack(_secret("slack_user_token"))
        return f"{who['user']} @ {who['team']}"

    def connect_clickup(self, token: str) -> str:
        token = token.strip()
        probe = ClickUp(lambda: token, self.settings)
        user = probe.user()
        set_secret("clickup_token", token)
        self.clickup = ClickUp(_secret("clickup_token"), self.settings)
        return user.get("username") or user.get("email") or "connected"

    def disconnect(self, service: str) -> None:
        if service == "google":
            self.google.disconnect()
        elif service == "slack":
            delete_secret("slack_user_token")
        elif service == "clickup":
            delete_secret("clickup_token")
