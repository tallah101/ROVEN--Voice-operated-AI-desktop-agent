import pytest

from config import Settings
from security.action_validator import safe_url, safe_user_path, validate_args
from security.audit_log import AuditLog, redact
from security.permission_manager import PermissionManager, Risk
from storage.database import Database
from storage.memory_store import MemoryStore


def test_low_risk_runs_without_asking():
    asked = []
    pm = PermissionManager(Settings(), confirm=lambda s: asked.append(s) or True)
    assert pm.decide("open_app", Risk.LOW, True, "x").allowed
    assert asked == []


def test_medium_asks_unless_trusted():
    s = Settings()
    pm = PermissionManager(s, confirm=lambda _: False)
    assert not pm.decide("create_folder", Risk.MEDIUM, True, "x").allowed
    s.trusted_actions = ["create_folder"]
    assert pm.decide("create_folder", Risk.MEDIUM, True, "x").allowed


def test_high_risk_always_asks_even_if_listed_as_trusted():
    s = Settings(trusted_actions=["power_action"])
    pm = PermissionManager(s, confirm=lambda _: False)
    assert not pm.decide("power_action", Risk.HIGH, False, "Shut down").allowed


def test_no_confirm_channel_denies():
    assert not PermissionManager(Settings(), confirm=None).decide("x", Risk.MEDIUM, True, "x").allowed


def test_redaction():
    text = "key sk-ant-abcdefghijklmnop123 and xoxb-1234567890-abc password: hunter2"
    out = redact(text)
    assert "sk-ant" not in out and "xoxb" not in out and "hunter2" not in out


def test_audit_log_redacts_args():
    log = AuditLog(Database(":memory:"))
    log.record("tool_executed", "x", {"token": "token=ya29.SECRETSECRET"})
    assert "SECRET" not in log.recent(1)[0]["args"]


def test_memory_refuses_credentials_and_supports_crud():
    m = MemoryStore(Database(":memory:"))
    with pytest.raises(ValueError):
        m.remember("my api key: sk-ant-abcdefghijklmnopqrst")
    i = m.remember("Mintsy is the wallet project")
    assert m.remember("Mintsy is the wallet project") == i      # deduped
    assert m.search("wallet")[0]["id"] == i
    assert m.update(i, "Mintsy is the crypto wallet project")
    assert m.forget(i) and m.all() == []


def test_paths_must_stay_in_home(tmp_path):
    assert safe_user_path("~/Documents").name == "Documents"
    with pytest.raises(PermissionError):
        safe_user_path("/etc/passwd" if not __import__("os").name == "nt" else r"C:\Windows\System32")


def test_urls():
    assert safe_url("example.com") == "https://example.com"
    with pytest.raises(ValueError):
        safe_url("file:///C:/secret.txt")
    with pytest.raises(ValueError):
        safe_url("javascript:alert(1)")
    assert safe_url("localhost:3000").startswith("https://localhost:3000")


def test_schema_validation():
    schema = {"type": "object", "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}},
              "required": ["percent"], "additionalProperties": False}
    assert validate_args(schema, {"percent": 40}) == []
    assert validate_args(schema, {"percent": 400})
    assert validate_args(schema, {"percent": 4, "cmd": "rm -rf"})
    assert validate_args(schema, "not a dict")
