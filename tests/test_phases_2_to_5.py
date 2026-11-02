import json
import threading
from types import SimpleNamespace

import pytest

from automation.browser_agent import check_fillable, click_risk, press_risk
from automation.documents import create_spreadsheet, markdown_to_docx, save_document, unique_path
from automation.ui_automation import control_risk
from config import Settings
from core.conversation_manager import ConversationManager
from core.reasoning_engine import ReasoningEngine
from core.tool_registry import Tool, ToolRegistry
from core.workflows import Workflows, keywords
from integrations.base import NotConnected
from security.audit_log import AuditLog
from security.permission_manager import PermissionManager, Risk
from storage.database import Database
from storage.memory_store import MemoryStore
from storage.workflow_store import WorkflowStore

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"], "additionalProperties": False}


# ---- risk rules ------------------------------------------------------------------------------------------
def test_ui_and_browser_risk_rules():
    assert control_risk("Send") == Risk.HIGH and control_risk("Delete file") == Risk.HIGH
    assert control_risk("Bold") == Risk.LOW
    assert click_risk({"text": "Place order"}) == Risk.HIGH and click_risk({"text": "Next page"}) == Risk.LOW
    assert press_risk({"key": "Enter"}) == Risk.MEDIUM and press_risk({"key": "Tab"}) == Risk.LOW
    for field in ("Password", "Card number", "CVV", "One-time code", "IBAN"):
        with pytest.raises(PermissionError):
            check_fillable(field)
    check_fillable("Search")


# ---- duplicate-action guard ------------------------------------------------------------------------------
def test_repeated_side_effect_requires_fresh_confirmation():
    asked = []
    s = Settings(trusted_actions=["make"])
    clock = [1000.0]
    reg = ToolRegistry(PermissionManager(s, confirm=lambda q: asked.append(q) or False),
                       AuditLog(Database(":memory:")), clock=lambda: clock[0])
    made = []
    reg.register(Tool("make", "d", SCHEMA, lambda n: made.append(n) or {"ok": True}, risk=Risk.MEDIUM))
    assert reg.execute("make", {"n": 1}).ok                 # trusted → no question
    assert not reg.execute("make", {"n": 1}).ok             # duplicate → asked, declined
    assert asked and asked[0].startswith("Repeat an action")
    assert made == [1]
    clock[0] += 700                                         # outside the window → trusted again
    assert reg.execute("make", {"n": 1}).ok and made == [1, 1]


def test_group_filtering():
    reg = ToolRegistry(PermissionManager(Settings()), AuditLog(Database(":memory:")))
    reg.register(Tool("a", "d", SCHEMA, lambda n: n))
    reg.register(Tool("b", "d", SCHEMA, lambda n: n, group="slack"))
    assert [t["name"] for t in reg.schemas({"gmail"})] == ["a"]
    assert [t["name"] for t in reg.schemas({"slack"})] == ["a", "b"]


# ---- workflow persistence -------------------------------------------------------------------------------
def test_workflow_store_recovery():
    st = WorkflowStore(Database(":memory:"))
    wid = st.begin("prepare Mintsy report")
    st.add_step(wid, "clickup_project_report", {"project": "Mintsy"}, True, "{...}")
    assert st.mark_interrupted_on_startup() == 1
    wf = st.pending_interrupted()
    assert wf["request"] == "prepare Mintsy report" and wf["steps"][0]["tool"] == "clickup_project_report"
    st.acknowledge(wf["id"])
    assert st.pending_interrupted() is None and st.latest_interrupted()["id"] == wid


# ---- workflows collectors -------------------------------------------------------------------------------
def test_keywords():
    assert keywords("Re: Mintsy wallet login issue for the client meeting") [:2] == ["Mintsy", "wallet"]


def test_briefing_reports_disconnected_services_instead_of_guessing():
    def nc(*a, **k):
        raise NotConnected("Slack is not connected")
    I = SimpleNamespace(
        calendar=SimpleNamespace(upcoming=lambda days: {"events": [{"title": "Standup"}]}),
        gmail=SimpleNamespace(search=lambda q, n: {"count": 0, "messages": []}),
        slack=SimpleNamespace(read_channel=nc),
        clickup=SimpleNamespace(user=nc),
    )
    out = Workflows(I, Settings(slack_briefing_channels=["mintsy"])).daily_briefing()
    assert out["calendar"] == [{"title": "Standup"}]
    assert out["slack"]["mintsy"] == {"not_connected": "Slack is not connected"}
    assert out["clickup"] == {"not_connected": "Slack is not connected"}


# ---- documents ---------------------------------------------------------------------------------------------
def test_markdown_report_to_docx_and_spreadsheet(tmp_path, monkeypatch):
    import docx
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    md = "# Summary\n**Done:** 3 tasks\n- BF - Wallet login\n1. Ship\n| Task | Status |\n|---|---|\n| UI | QA |"
    out = save_document("Mintsy Progress", md, "~/Reports", "docx")
    d = docx.Document(out["saved"])
    texts = [p.text for p in d.paragraphs]
    assert "Mintsy Progress" in texts and "Summary" in texts and "BF - Wallet login" in texts
    assert d.tables[0].cell(1, 1).text == "QA"
    again = save_document("Mintsy Progress", "x", "~/Reports", "md")
    assert again["saved"].endswith("Mintsy Progress.md")
    third = save_document("Mintsy Progress", "x", "~/Reports", "docx")
    assert third["saved"].endswith("Mintsy Progress (2).docx")
    xl = create_spreadsheet("~/Reports/team", {"Tasks": [["Name", "Hours"], ["BF", 3]]})
    assert xl["saved"].endswith("team.xlsx") and xl["verified"]


# ---- reasoning loop with a fake model ----------------------------------------------------------------------
class Block(SimpleNamespace):
    def model_dump(self, **kw):
        return {k: v for k, v in vars(self).items() if v is not None}


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=str)))
        return self.script.pop(0)


def make_engine(script, store=None):
    s = Settings(enable_web_research=True)
    db = Database(":memory:")
    reg = ToolRegistry(PermissionManager(s), AuditLog(db))
    reg.register(Tool("add_one", "d", SCHEMA, lambda n: {"result": n + 1}, long_running=True))
    reg.register(Tool("slack_only", "d", SCHEMA, lambda n: n, group="slack"))
    client = FakeClient(script)
    eng = ReasoningEngine(s, reg, MemoryStore(db), ConversationManager(), client=client, workflow_store=store)
    return eng, client


def test_engine_tool_loop_pause_turn_and_reply_parsing():
    store = WorkflowStore(Database(":memory:"))
    script = [
        SimpleNamespace(stop_reason="tool_use", content=[Block(type="text", text="On it"),
                                                         Block(type="tool_use", id="tu1", name="add_one", input={"n": 41})]),
        SimpleNamespace(stop_reason="pause_turn", content=[Block(type="server_tool_use", id="s1", name="web_search", input={"query": "x"})]),
        SimpleNamespace(stop_reason="end_turn", content=[Block(type="text", text="[lang=ur-Latn] Jawab 42 hai. <speak>جواب بیالیس ہے۔</speak>")]),
    ]
    eng, client = make_engine(script, store)
    progress = []
    reply = eng.run("41 mein ek jama karo", "hi", threading.Event(), lambda s, long: progress.append((s, long)))
    assert reply.display == "Jawab 42 hai." and reply.lang == "ur-Latn" and reply.speech == "جواب بیالیس ہے۔"
    tool_names = [t["name"] for t in client.requests[0]["tools"]]
    assert "add_one" in tool_names and "web_search" in tool_names and "slack_only" not in tool_names
    assert client.requests[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert client.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    second_msgs = client.requests[1]["messages"]
    assert second_msgs[-1]["content"][0] == {"type": "tool_result", "tool_use_id": "tu1",
                                             "content": '{"result": 42}', "is_error": False}
    assert progress[0][1] is True                       # long-running tool announced
    wf = store.recent(1)[0]
    assert wf["status"] == "done" and store.get(wf["id"])["steps"][0]["tool"] == "add_one"


def test_engine_stops_on_cancel_and_marks_workflow():
    store = WorkflowStore(Database(":memory:"))
    eng, _ = make_engine([], store)
    ev = threading.Event()
    ev.set()
    assert eng.run("anything", "en", ev).display == "Stopped."
    assert store.recent(1)[0]["status"] == "cancelled"


def test_unique_path(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    assert unique_path(p).name == "a (2).txt"


def test_complete_registry_builds_and_every_schema_is_valid():
    from jsonschema import Draft202012Validator

    from automation.application_control import AppCatalog
    from automation.browser_agent import BrowserAgent
    from core.tools_builtin import build_registry
    from core.tools_integrations import register_integration_tools
    s = Settings()
    db = Database(":memory:")
    store = WorkflowStore(db)
    reg = build_registry(PermissionManager(s), AuditLog(db), MemoryStore(db), AppCatalog(), store)
    register_integration_tools(reg, SimpleNamespace(), SimpleNamespace(), s, BrowserAgent(s))
    from core.tools_general import register_general_tools
    from storage.reminders import Reminders
    register_general_tools(reg, s, show=lambda p: None, reminders=Reminders(db))
    for sch in reg.schemas():
        Draft202012Validator.check_schema(sch["input_schema"])
        assert len(sch["description"]) > 10
    names = reg.names()
    for must in ("gmail_send_draft", "slack_read_channel", "clickup_create_task", "calendar_events", "drive_read",
                 "daily_briefing_data", "click_control", "browser_click", "save_document", "get_interrupted_task",
                 "run_script", "browser_history", "look_at_screen", "click_at", "show_results", "set_reminder"):
        assert must in names
    assert "gmail_send_draft" in reg.trustable_medium_tools() and "slack_send_message" in reg.trustable_medium_tools()
    assert "power_action" not in reg.trustable_medium_tools() and "browser_upload" not in reg.trustable_medium_tools()
    assert "run_script" in reg.trustable_medium_tools() and "click_at" not in reg.trustable_medium_tools()
    assert len(names) == len(set(names))
    assert len(reg.schemas(set())) < len(reg.schemas())   # integration tools hidden when nothing is connected
