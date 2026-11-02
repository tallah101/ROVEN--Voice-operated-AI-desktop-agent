"""Shared HTTP layer for integrations: retries, rate limits (429 / Retry-After), clear errors."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

log = logging.getLogger(__name__)


class NotConnected(RuntimeError):
    """The integration has no valid credentials. The message tells the user how to connect it."""


class ApiError(RuntimeError):
    def __init__(self, service: str, status: int, message: str) -> None:
        super().__init__(f"{service} error {status}: {message}")
        self.service = service
        self.status = status


def _retry_after(resp, attempt: int) -> float:
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return min(30.0, max(1.0, float(header)))
        except ValueError:
            pass
    reset = resp.headers.get("X-RateLimit-Reset")      # ClickUp: epoch seconds
    if reset:
        try:
            return min(30.0, max(1.0, float(reset) - time.time()))
        except ValueError:
            pass
    return min(30.0, 2.0 ** attempt)


def _error_text(resp) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)
            return str(data.get("err") or err or data.get("message") or data)[:300]
    except ValueError:
        pass
    return resp.text[:300]


class RestClient:
    def __init__(self, service: str, base_url: str, session_factory: Callable[[], Any],
                 max_retries: int = 4, sleep: Callable[[float], None] = time.sleep) -> None:
        self.service = service
        self.base_url = base_url
        self.session_factory = session_factory
        self.max_retries = max_retries
        self.sleep = sleep

    def request(self, method: str, path: str, *, params=None, json=None, data=None, headers=None, raw: bool = False):
        session = self.session_factory()
        url = path if path.startswith("http") else self.base_url + path.lstrip("/")
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = session.request(method, url, params=params, json=json, data=data, headers=headers, timeout=30)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last = exc
                self.sleep(min(10.0, 2.0 ** attempt))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = _retry_after(resp, attempt)
                log.warning("%s %s -> %s; retrying in %.0fs", self.service, path, resp.status_code, wait)
                last = ApiError(self.service, resp.status_code, "rate limited" if resp.status_code == 429 else "server error")
                self.sleep(wait)
                continue
            if resp.status_code == 401:
                raise NotConnected(f"{self.service} rejected the saved credentials. Reconnect it in Dashboard → Integrations.")
            if resp.status_code >= 400:
                raise ApiError(self.service, resp.status_code, _error_text(resp))
            if raw:
                return resp
            return resp.json() if resp.content else {}
        if isinstance(last, ApiError):
            raise last
        raise ApiError(self.service, 0, f"network problem ({last}). Check the internet connection.")
