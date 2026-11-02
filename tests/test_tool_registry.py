import threading

from config import Settings
from core.tool_registry import Tool, ToolRegistry
from security.audit_log import AuditLog
from security.permission_manager import PermissionManager, Risk
from storage.database import Database

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"], "additionalProperties": False}


def make(confirm=lambda s: True):
    audit = AuditLog(Database(":memory:"))
    return ToolRegistry(PermissionManager(Settings(), confirm=confirm), audit), audit


def test_unknown_tool_rejected():
    reg, audit = make()
    res = reg.execute("run_shell", {"cmd": "format c:"})
    assert not res.ok and "Unknown tool" in res.content
    assert audit.recent(1)[0]["event"] == "tool_rejected"


def test_invalid_args_rejected_before_running():
    reg, _ = make()
    calls = []
    reg.register(Tool("double", "d", SCHEMA, lambda n: calls.append(n) or n * 2))
    assert not reg.execute("double", {"n": "x"}).ok
    assert calls == []
    assert reg.execute("double", {"n": 4}).content == "8"


def test_denied_tool_never_runs_and_says_so():
    reg, _ = make(confirm=lambda s: False)
    ran = []
    reg.register(Tool("danger", "d", SCHEMA, lambda n: ran.append(n), risk=Risk.HIGH))
    res = reg.execute("danger", {"n": 1})
    assert not res.ok and ran == [] and "Do not tell the user it was done" in res.content


def test_dynamic_risk():
    asked = []
    reg, _ = make(confirm=lambda s: asked.append(s) or True)
    reg.register(Tool("t", "d", SCHEMA, lambda n: n, risk=lambda a: Risk.HIGH if a["n"] > 5 else Risk.LOW))
    reg.execute("t", {"n": 1})
    assert asked == []
    reg.execute("t", {"n": 9})
    assert len(asked) == 1


def test_tool_exception_is_reported_not_raised():
    reg, _ = make()
    reg.register(Tool("boom", "d", SCHEMA, lambda n: 1 / 0))
    res = reg.execute("boom", {"n": 1})
    assert not res.ok and "division" in res.content


def test_cancel_blocks_execution():
    reg, _ = make()
    reg.register(Tool("t", "d", SCHEMA, lambda n: n))
    ev = threading.Event()
    ev.set()
    assert not reg.execute("t", {"n": 1}, ev).ok


def test_ok_false_result_reported_as_error():
    reg, _ = make()
    reg.register(Tool("t", "d", SCHEMA, lambda n: {"ok": False, "error": "no app"}))
    assert not reg.execute("t", {"n": 1}).ok


def test_full_builtin_registry_builds_with_valid_schemas():
    from jsonschema import Draft202012Validator

    from automation.application_control import AppCatalog
    from core.tools_builtin import build_registry
    from storage.memory_store import MemoryStore
    db = Database(":memory:")
    reg = build_registry(PermissionManager(Settings()), AuditLog(db), MemoryStore(db), AppCatalog())
    for s in reg.schemas():
        Draft202012Validator.check_schema(s["input_schema"])
    assert "power_action" in reg.names()
    assert "power_action" not in reg.trustable_medium_tools()
    assert "create_folder" in reg.trustable_medium_tools()
