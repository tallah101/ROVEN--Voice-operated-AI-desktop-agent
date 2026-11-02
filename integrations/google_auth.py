"""Google OAuth (installed-app flow, loopback redirect). One consent covers Gmail, Calendar and Drive.
The token (incl. refresh token) is stored in Windows Credential Manager and refreshed automatically."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import requests

from integrations.base import NotConnected
from security.credentials import delete_secret, get_secret, set_secret

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",          # read, draft, send, label (no permanent delete)
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
SECRET = "google_token"


class GoogleAuth:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._session = None
        self._lock = threading.Lock()

    def connected(self) -> bool:
        try:
            return bool(get_secret(SECRET))
        except Exception:
            return False

    def _credentials(self):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        raw = get_secret(SECRET)
        if not raw:
            raise NotConnected("Google (Gmail, Calendar, Drive) is not connected. Connect it in Dashboard → Integrations.")
        creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
        if not creds.valid:
            if not creds.refresh_token:
                raise NotConnected("Google access expired. Reconnect it in Dashboard → Integrations.")
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                raise NotConnected(f"Google access was revoked or expired ({exc}). Reconnect in Dashboard → Integrations.")
        return creds

    def session(self):
        with self._lock:
            if self._session is None:
                from google.auth.transport.requests import AuthorizedSession
                self._session = AuthorizedSession(self._credentials())
            return self._session

    def connect(self) -> None:
        path = self.settings.google_client_secrets_path
        if not path or not Path(path).exists():
            raise FileNotFoundError("Choose your Google OAuth client JSON file first (README → Google setup).")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline", open_browser=True)
        set_secret(SECRET, creds.to_json())
        with self._lock:
            self._session = None

    def disconnect(self) -> None:
        raw = get_secret(SECRET)
        if raw:
            try:
                token = json.loads(raw).get("refresh_token") or json.loads(raw).get("token")
                requests.post("https://oauth2.googleapis.com/revoke", params={"token": token}, timeout=10)
            except Exception:
                pass
        delete_secret(SECRET)
        with self._lock:
            self._session = None
