import base64
from datetime import datetime

import pytest

from config import Settings
from integrations.base import ApiError, NotConnected, RestClient
from integrations.clickup import ClickUp, build_task_name, link_messages_to_tasks, normalize_task, project_metrics
from integrations.gmail import Gmail, build_mime, html_to_text, parse_message, recipients_of
from integrations.google_drive import drive_query
from integrations.slack import Slack, format_text, time_window
from tests.fakes import FakeResponse, FakeSession

DAY = 86_400_000
NOW = 1_780_000_000_000


def client(service, base, routes):
    s = FakeSession(routes)
    return RestClient(service, base, lambda: s, sleep=lambda _: None), s


# ---- HTTP layer -------------------------------------------------------------------------------------
def test_rate_limit_is_retried_then_succeeds():
    http, s = client("X", "https://x/", {("GET", "thing"): [FakeResponse(429, headers={"Retry-After": "1"}),
                                                            FakeResponse(200, {"ok": 1})]})
    assert http.request("GET", "thing") == {"ok": 1}
    assert len(s.calls) == 2


def test_401_becomes_not_connected_and_4xx_is_api_error():
    http, _ = client("X", "https://x/", {("GET", "a"): FakeResponse(401), ("GET", "b"): FakeResponse(404, {"err": "nope"})})
    with pytest.raises(NotConnected):
        http.request("GET", "a")
    with pytest.raises(ApiError, match="nope"):
        http.request("GET", "b")


def test_persistent_server_errors_give_up():
    http, s = client("X", "https://x/", {("GET", "a"): lambda p, j: FakeResponse(503)})
    with pytest.raises(ApiError):
        http.request("GET", "a")
    assert len(s.calls) == 5


# ---- Gmail --------------------------------------------------------------------------------------------
def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


MSG = {"id": "m1", "threadId": "t1", "labelIds": ["INBOX", "UNREAD"], "snippet": "Hi &amp; hello",
       "payload": {"mimeType": "multipart/mixed", "headers": [
           {"name": "From", "value": "Ahmed Khan <ahmed@client.com>"}, {"name": "To", "value": "me@co.com"},
           {"name": "Cc", "value": "Sara <sara@co.com>"}, {"name": "Subject", "value": "Mintsy report"},
           {"name": "Message-ID", "value": "<abc@mail>"}],
           "parts": [{"mimeType": "text/html", "body": {"data": b64("<p>Please send the <b>report</b> by Friday</p><script>x</script>")}},
                     {"mimeType": "application/pdf", "filename": "spec.pdf", "body": {"attachmentId": "A1", "size": 1200}}]}}


def test_parse_message_html_fallback_and_attachments():
    p = parse_message(MSG)
    assert p["from"].startswith("Ahmed") and p["unread"] and p["subject"] == "Mintsy report"
    assert "Please send the report by Friday" in p["body"] and "x" not in p["body"].split("Friday")[-1]
    assert p["attachments"] == [{"filename": "spec.pdf", "mime_type": "application/pdf", "size": 1200}]
    assert p["snippet"] == "Hi & hello"
    assert recipients_of(p) == ["me@co.com", "sara@co.com"]


def test_html_to_text():
    assert html_to_text("<div>a</div><div>b &lt;3</div>") == "a\nb <3"


def test_build_mime_rejects_uncertain_recipients():
    with pytest.raises(ValueError, match="complete email address"):
        build_mime(["Ahmed"], "s", "b")
    raw = build_mime(["a@b.com"], "Re: x", "hello", in_reply_to="<id@x>")
    decoded = base64.urlsafe_b64decode(raw).decode()
    assert "In-Reply-To: <id@x>" in decoded and "To: a@b.com" in decoded


def test_reply_draft_threads_and_send_verifies():
    gm_routes = {
        ("GET", "messages/m1"): MSG,
        ("POST", "drafts"): {"id": "d1"},
        ("POST", "drafts/send"): {"id": "s1", "threadId": "t1"},
        ("GET", "messages/s1"): {"id": "s1", "labelIds": ["SENT"]},
    }
    http, s = client("Gmail", "https://g/", gm_routes)
    gm = Gmail(auth=None, http=http)
    d = gm.create_draft(["ahmed@client.com"], body="Will do.", reply_to_message_id="m1")
    sent_body = s.calls[-1]["json"]["message"]
    assert d["subject"] == "Re: Mintsy report" and sent_body["threadId"] == "t1"
    assert "In-Reply-To: <abc@mail>" in base64.urlsafe_b64decode(sent_body["raw"]).decode()
    assert gm.send_draft("d1")["sent"] is True


# ---- Slack -------------------------------------------------------------------------------------------
def test_slack_format_text():
    names = {"U1": "Osama"}
    out = format_text("<@U1> fixed <#C9|mintsy> see <https://x.io|PR> &amp; <!here>", lambda u: names.get(u, u))
    assert out == "@Osama fixed #mintsy see PR (https://x.io) & @here"


def test_time_window():
    now = datetime(2026, 11, 4, 15, 30)
    start, end = time_window("today", now)
    assert datetime.fromtimestamp(start) == datetime(2026, 11, 4) and end is None
    start, end = time_window("yesterday", now)
    assert datetime.fromtimestamp(start) == datetime(2026, 11, 3) and datetime.fromtimestamp(end) == datetime(2026, 11, 4)
    assert datetime.fromtimestamp(time_window("6h", now)[0]) == datetime(2026, 11, 4, 9, 30)
    assert datetime.fromtimestamp(time_window("this_week", now)[0]) == datetime(2026, 11, 2)
    with pytest.raises(ValueError):
        time_window("whenever", now)


def test_slack_read_channel_with_threads_and_inaccessible_channel():
    routes = {
        ("GET", "conversations.list"): {"ok": True, "channels": [
            {"id": "C1", "name": "mintsy", "is_member": True}, {"id": "C2", "name": "secret", "is_private": True}]},
        ("GET", "conversations.history"): lambda p, j: (
            {"ok": True, "messages": [{"ts": "1780000100.0", "user": "U1", "text": "Backend done, <@U2> please QA", "reply_count": 1},
                                      {"ts": "1780000000.0", "user": "U2", "text": "morning"}]}
            if p["channel"] == "C1" else {"ok": False, "error": "not_in_channel"}),
        ("GET", "conversations.replies"): {"ok": True, "messages": [
            {"ts": "1780000100.0", "user": "U1", "text": "Backend done"}, {"ts": "1780000200.0", "user": "U2", "text": "QA tomorrow"}]},
        ("GET", "users.info"): lambda p, j: {"ok": True, "user": {"profile": {"real_name": {"U1": "Osama", "U2": "Hareem"}[p["user"]]}}},
    }
    http, _ = client("Slack", "https://slack.com/api/", routes)
    sl = Slack(lambda: "xoxp-test", http=http)
    data = sl.read_channel("Mintsy", "today")
    assert data["channel"] == "#mintsy" and data["message_count"] == 2
    assert data["messages"][0]["text"] == "morning"                       # oldest first
    assert data["messages"][1]["text"] == "Backend done, @Hareem please QA"
    assert data["messages"][1]["replies"][0]["text"] == "QA tomorrow"
    with pytest.raises(ApiError, match="isn't accessible"):
        sl.read_channel("secret")
    with pytest.raises(LookupError):
        sl.read_channel("nonexistent-channel-xyz")


def test_slack_auth_error_and_not_connected():
    http, _ = client("Slack", "https://slack.com/api/", {("GET", "auth.test"): {"ok": False, "error": "invalid_auth"}})
    with pytest.raises(NotConnected):
        Slack(lambda: "xoxp-bad", http=http).me()
    with pytest.raises(NotConnected):
        Slack(lambda: None).me()


# ---- ClickUp -----------------------------------------------------------------------------------------
def T(id, name, status="to do", stype="open", due=None, updated=NOW, est=None, spent=None, assignees=("Osama",),
      closed=None, tags=(), deps=()):
    return normalize_task({"id": id, "name": name, "status": {"status": status, "type": stype},
                           "due_date": str(due) if due else None, "date_updated": str(updated),
                           "date_closed": str(closed) if closed else None,
                           "time_estimate": est and est * 3_600_000, "time_spent": spent and spent * 3_600_000,
                           "assignees": [{"username": a} for a in assignees], "tags": [{"name": t} for t in tags],
                           "dependencies": [{"task_id": id, "depends_on": d} for d in deps], "url": f"https://app/{id}"})


def test_project_metrics_buckets_and_honest_gaps():
    tasks = [
        T("1", "BF - Wallet login", "qa", "custom", due=NOW - 2 * DAY, est=4, spent=6),
        T("2", "NR - Export CSV", "in progress", "custom", est=8, spent=3),
        T("3", "CR - Logo change", "to do", updated=NOW - 10 * DAY, assignees=()),
        T("4", "UI - Navbar", "complete", "closed", closed=NOW - DAY, est=2, spent=2),
        T("5", "IMP - Caching", "to do", deps=("2",)),
        T("6", "INV - Crash", "blocked", "custom"),
    ]
    m = project_metrics(tasks, NOW, stale_days=5)
    assert m["counts"] == {"completed": 1, "qa": 1, "blocked": 2, "in_progress": 1, "todo": 1}
    assert [t["id"] for t in m["overdue"]] == ["1"] and m["overdue"][0]["days_overdue"] == 2
    assert [t["id"] for t in m["over_estimate"]] == ["1"] and m["over_estimate"][0]["over_by_h"] == 2
    assert [t["id"] for t in m["no_update_in_days"]["tasks"]] == ["3"]
    assert m["estimate_vs_tracked"] == {"tasks_with_both": 3, "estimated_h": 14, "tracked_h": 11}
    assert m["data_gaps"]["without_assignee"] == 1 and m["data_gaps"]["without_estimate"] == 3
    assert "(unassigned)" in m["workload"] and m["workload"]["Osama"]["overdue"] == 1


def test_task_naming_convention():
    p = Settings().clickup_prefixes
    assert build_task_name("bf", "Wallet login fails", p) == "BF - Wallet login fails"
    assert build_task_name("BF", "BF: Wallet login fails", p) == "BF - Wallet login fails"
    assert build_task_name("CR", "x", p, "[{prefix}] {title}") == "[CR] x"
    with pytest.raises(ValueError):
        build_task_name("ZZ", "x", p)


def test_link_slack_messages_to_tasks():
    tasks = [T("abc123", "BF - Wallet login issue on Safari"), T("zz9", "NR - Export")]
    msgs = [{"ts": "1", "user": "Osama", "text": "Fixed the wallet login issue on safari, ready for QA"},
            {"ts": "2", "user": "Ali", "text": "see https://app.clickup.com/t/zz9"},
            {"ts": "3", "user": "Ali", "text": "lunch?"}]
    links = link_messages_to_tasks(msgs, tasks)
    assert [l["task_ids"] for l in links] == [["abc123"], ["zz9"]]


def test_clickup_find_lists_by_space_and_pagination():
    s = Settings()
    routes = {
        ("GET", "team"): {"teams": [{"id": 9, "members": [{"user": {"id": 1, "username": "Osama"}},
                                                          {"user": {"id": 2, "username": "Muqeet"}}]}]},
        ("GET", "team/9/space"): {"spaces": [{"id": "s1", "name": "Mintsy"}, {"id": "s2", "name": "Helius"}]},
        ("GET", "space/s1/folder"): {"folders": [{"name": "Sprint", "lists": [{"id": "L1", "name": "Backlog"}]}]},
        ("GET", "space/s2/folder"): {"folders": []},
        ("GET", "space/s1/list"): {"lists": [{"id": "L2", "name": "Bugs"}]},
        ("GET", "space/s2/list"): {"lists": [{"id": "L3", "name": "General"}]},
        ("GET", "team/9/task"): lambda p, j: {"tasks": [{"id": f"t{p['page']}{i}", "name": "x", "status": {}} for i in range(100 if p["page"] == 0 else 3)],
                                              "last_page": p["page"] == 1},
    }
    http, _ = client("ClickUp", "https://api/", routes)
    cu = ClickUp(lambda: "pk_x", s, http=http)
    assert {l["id"] for l in cu.find_lists("mintsy")} == {"L1", "L2"}
    assert len(cu.search_tasks(list_ids=["L1"])) == 103
    assert cu.resolve_member_ids(["muqeet"]) == [2]
    with pytest.raises(LookupError):
        cu.resolve_member_ids(["Zebediah"])


def test_drive_query_escaping():
    assert drive_query("Ali's report") == "(name contains 'Ali\\'s report' or fullText contains 'Ali\\'s report') and trashed = false"
