"""Argument validation for every tool call: JSON schema, safe paths, safe URLs."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:(?!\d)", re.I)   # "javascript:", "file:" — but not "localhost:3000"

from jsonschema import Draft202012Validator


def validate_args(schema: dict, args) -> list[str]:
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    validator = Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in validator.iter_errors(args)]


def safe_user_path(raw: str) -> Path:
    """Resolve a path and require it to be inside the user's home folder."""
    home = Path.home().resolve()
    text = raw.strip().strip('"')
    if text == "~" or text.startswith(("~/", "~\\")):
        path = home / text[2:]          # same home as the check below (expanduser may differ)
    else:
        path = Path(text)
    if not path.is_absolute():
        path = home / path
    path = path.resolve()
    if path != home and home not in path.parents:
        raise PermissionError(f"ROVEN only manages files inside {home}.")
    return path


def safe_url(raw: str) -> str:
    url = raw.strip()
    if _SCHEME.match(url) and not url.lower().startswith(("http://", "https://")):
        raise ValueError("Only http(s) web addresses can be opened.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Only http(s) web addresses can be opened.")
    return url
