"""Tools for Gmail, Slack, ClickUp, Calendar, Drive, documents, UI Automation, browser agent and workflows."""
from __future__ import annotations

from datetime import datetime
from email.utils import getaddresses

from automation import browser_agent as ba
from automation import documents as docs
from automation import keyboard_mouse as km
from automation import ui_automation as uia
from core.tool_registry import Tool
from integrations.clickup import build_task_name, project_metrics
from integrations.gmail import recipients_of
from security.permission_manager import Risk


def S(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


STR = {"type": "string", "minLength": 1}
EMAIL = {"type": "string", "pattern": r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$"}
EMAILS = {"type": "array", "items": EMAIL, "maxItems": 50}
DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
SINCE = {"type": "string", "description": "today | yesterday | this_week | <n>h | <n>d | YYYY-MM-DD"}


def _date_ms(d: str | None, end_of_day: bool = True) -> int | None:
    if not d:
        return None
    dt = datetime.fromisoformat(d)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59)
    return int(dt.timestamp() * 1000)


def register_integration_tools(r, I, W, settings, browser: ba.BrowserAgent) -> None:
    add = r.register

    # ===== Gmail ===================================================================================
    def send_risk(args):
        d = I.gmail.get_draft(args["draft_id"])
        rcpts = recipients_of(d)
        domains = {a.split("@")[-1] for a in rcpts}
        trusted = {x.lower() for x in settings.trusted_email_domains}
        return Risk.MEDIUM if rcpts and trusted and domains <= trusted else Risk.HIGH

    def send_summary(args):
        d = I.gmail.get_draft(args["draft_id"])
        return f"Send email to {d['to']}{' cc ' + d['cc'] if d['cc'] else ''}, subject '{d['subject']}': {d['body'][:160]}"

    add(Tool("gmail_search", "Search Gmail with Gmail query syntax (from:, to:, subject:, is:unread, newer_than:2d, "
             "has:attachment, label:, in:sent). Empty query = inbox.", S({"query": {"type": "string"},
             "max_results": {"type": "integer", "minimum": 1, "maximum": 50}}),
             lambda query="", max_results=10: I.gmail.search(query, max_results), group="gmail"))
    add(Tool("gmail_read_message", "Read one email in full (sender, date, body, attachments).",
             S({"message_id": STR}, ("message_id",)), lambda message_id: I.gmail.read(message_id), group="gmail", untrusted_output=True))
    add(Tool("gmail_read_thread", "Read a whole email conversation, e.g. to see whether anyone replied.",
             S({"thread_id": STR}, ("thread_id",)), lambda thread_id: I.gmail.read_thread(thread_id), group="gmail", untrusted_output=True))
    add(Tool("gmail_find_contact", "Find email addresses for a person by name from past correspondence. "
             "Use before drafting to anyone the user names without an address.",
             S({"name": STR}, ("name",)), lambda name: I.gmail.find_contact(name), group="gmail"))
    add(Tool("gmail_create_draft", "Create a Gmail draft (not sent). For replies pass reply_to_message_id so it threads. "
             "Recipients must be complete, certain addresses.",
             S({"to": {**EMAILS, "minItems": 1}, "subject": {"type": "string"}, "body": STR, "cc": EMAILS, "bcc": EMAILS,
                "attachments": {"type": "array", "items": STR}, "reply_to_message_id": {"type": "string"}}, ("to", "body")),
             lambda **a: I.gmail.create_draft(**a), group="gmail",
             summarize=lambda a: f"Draft email to {', '.join(a['to'])}"))
    add(Tool("gmail_update_draft", "Revise an existing draft (e.g. 'make it shorter'). Omitted fields stay the same.",
             S({"draft_id": STR, "to": EMAILS, "subject": {"type": "string"}, "body": {"type": "string"},
                "cc": EMAILS, "bcc": EMAILS, "attachments": {"type": "array", "items": STR}}, ("draft_id",)),
             lambda **a: I.gmail.update_draft(**a), group="gmail"))
    add(Tool("gmail_get_draft", "Read a draft back, e.g. to read it aloud for review.", S({"draft_id": STR}, ("draft_id",)),
             lambda draft_id: I.gmail.get_draft(draft_id), group="gmail"))
    add(Tool("gmail_forward_as_draft", "Prepare a forward of an email (with attachments) as a draft.",
             S({"message_id": STR, "to": {**EMAILS, "minItems": 1}, "note": {"type": "string"}}, ("message_id", "to")),
             lambda **a: I.gmail.forward_draft(**a), group="gmail"))
    add(Tool("gmail_send_draft", "Send a draft. The user is asked to confirm recipients and content unless all recipients "
             "are in their trusted internal domains and they trusted this action.",
             S({"draft_id": STR}, ("draft_id",)), lambda draft_id: I.gmail.send_draft(draft_id), group="gmail",
             risk=send_risk, trust_listed=True, summarize=send_summary))
    add(Tool("gmail_organize", "Archive, mark read/unread, star/unstar or move emails back to the inbox.",
             S({"message_ids": {"type": "array", "items": STR, "minItems": 1, "maxItems": 100},
                "action": {"enum": ["archive", "mark_read", "mark_unread", "star", "unstar", "move_to_inbox"]}},
               ("message_ids", "action")), lambda message_ids, action: I.gmail.modify(message_ids, action), group="gmail",
             risk=lambda a: Risk.MEDIUM if a["action"] == "archive" and len(a["message_ids"]) > 5 else Risk.LOW))

    # ===== Slack ===================================================================================
    def slack_send_risk(args):
        info = I.slack.target_info(args["target"])
        return Risk.HIGH if info["external"] else Risk.MEDIUM

    add(Tool("slack_list_channels", "List Slack channels you can access, optionally fuzzy-filtered by name.",
             S({"filter": {"type": "string"}}), lambda filter="": I.slack.list_channels(filter), group="slack"))
    add(Tool("slack_read_channel", "Read a channel's messages in a time window, with thread replies, authors and times.",
             S({"channel": STR, "since": SINCE, "limit": {"type": "integer", "minimum": 1, "maximum": 400},
                "include_threads": {"type": "boolean"}}, ("channel",)),
             lambda **a: I.slack.read_channel(**a), group="slack", long_running=True, untrusted_output=True))
    add(Tool("slack_read_thread", "Read all replies in a Slack thread.", S({"channel": STR, "thread_ts": STR},
             ("channel", "thread_ts")), lambda channel, thread_ts: I.slack.read_thread(channel, thread_ts), group="slack", untrusted_output=True))
    add(Tool("slack_search", "Search Slack messages you can access. Modifiers: in:#channel from:@name after:YYYY-MM-DD "
             "before: on: has:link. Use to find who said what about a topic.",
             S({"query": STR, "count": {"type": "integer", "minimum": 1, "maximum": 100}}, ("query",)),
             lambda query, count=20: I.slack.search(query, count), group="slack", untrusted_output=True))
    add(Tool("slack_find_user", "Find a Slack user by name.", S({"name": STR}, ("name",)),
             lambda name: I.slack.find_user(name), group="slack"))
    add(Tool("slack_send_message", "Post a message to a channel ('#name') or DM ('@person'), optionally in a thread.",
             S({"target": STR, "text": {"type": "string", "minLength": 1, "maxLength": 4000}, "thread_ts": {"type": "string"}},
               ("target", "text")), lambda **a: I.slack.send_message(**a), group="slack", risk=slack_send_risk,
             trust_listed=True, summarize=lambda a: f"Post to {a['target']} on Slack: \"{a['text'][:160]}\""))
    add(Tool("slack_share_file", "Upload a local file to a Slack channel or DM.",
             S({"target": STR, "path": STR, "comment": {"type": "string"}}, ("target", "path")),
             lambda **a: I.slack.upload_file(**a), group="slack", risk=Risk.HIGH, trustable=False,
             summarize=lambda a: f"Share {a['path']} to {a['target']} on Slack"))

    # ===== ClickUp =================================================================================
    prefixes = settings.clickup_prefixes
    add(Tool("clickup_find_project", "Find ClickUp lists for a project/space/folder name.", S({"query": STR}, ("query",)),
             lambda query: I.clickup.find_lists(query), group="clickup"))
    add(Tool("clickup_members", "Find ClickUp workspace members by name (empty = all).", S({"name": {"type": "string"}}),
             lambda name="": I.clickup.find_member(name) if name else I.clickup.members(), group="clickup"))

    def search_tasks(project=None, assignee=None, statuses=None, include_closed=False, due_before=None,
                     updated_since=None, name_contains=None, mine=False):
        list_ids = [l["id"] for l in I.clickup.find_lists(project)] if project else None
        if project and not list_ids:
            return {"ok": False, "error": f"No ClickUp project matches '{project}'."}
        assignees = [I.clickup.user()["id"]] if mine else (I.clickup.resolve_member_ids([assignee]) if assignee else None)
        tasks = I.clickup.search_tasks(list_ids, assignees, statuses, include_closed, _date_ms(due_before),
                                       _date_ms(updated_since, False))
        if name_contains:
            tasks = [t for t in tasks if name_contains.lower() in t["name"].lower()]
        return {"count": len(tasks), "tasks": [{k: v for k, v in t.items() if not k.endswith("_ms")} for t in tasks[:80]],
                "truncated": len(tasks) > 80}

    add(Tool("clickup_search_tasks", "Find tasks by project, assignee, status, due date, recency or name. mine=true for the "
             "user's own tasks. Closed tasks are excluded unless include_closed.",
             S({"project": {"type": "string"}, "assignee": {"type": "string"}, "mine": {"type": "boolean"},
                "statuses": {"type": "array", "items": STR}, "include_closed": {"type": "boolean"},
                "due_before": DATE, "updated_since": DATE, "name_contains": {"type": "string"}}),
             search_tasks, group="clickup", long_running=True))
    add(Tool("clickup_get_task", "Full task details incl. description, subtasks, dependencies and recent comments "
             "(comments often record delay reasons).", S({"task_id": STR}, ("task_id",)),
             lambda task_id: I.clickup.get_task(task_id), group="clickup"))

    def report(project, stale_days=None):
        lists, tasks = I.clickup.project_tasks(project)
        metrics = project_metrics(tasks, stale_days=stale_days or settings.stale_task_days)
        for t in metrics["overdue"][:6] + metrics["blocked"][:6]:
            try:
                t["recent_comments"] = I.clickup.get_task(t["id"], comments=3).get("recent_comments", [])
            except Exception:
                pass
        return {"lists": [l["path"] for l in lists], **metrics}

    add(Tool("clickup_project_report", "Computed project status from ClickUp: buckets (done/QA/blocked/in progress/todo), "
             "overdue, stale, estimate vs tracked hours, workload per person, data gaps, recent comments on problem tasks.",
             S({"project": STR, "stale_days": {"type": "integer", "minimum": 1, "maximum": 60}}, ("project",)),
             report, group="clickup", long_running=True))

    def create_task(list_id, category, title, description="", assignees=None, due_date=None, priority=None, tags=None):
        name = build_task_name(category, title, prefixes, settings.clickup_title_format)
        ids = I.clickup.resolve_member_ids(assignees) if assignees else None
        return I.clickup.create_task(list_id, name, description, ids, _date_ms(due_date), priority, tags)

    add(Tool("clickup_create_task", "Create a task. category is the naming prefix: "
             + ", ".join(f"{k}={v}" for k, v in prefixes.items()) + ". title without the prefix.",
             S({"list_id": STR, "category": {"enum": sorted(prefixes)}, "title": STR, "description": {"type": "string"},
                "assignees": {"type": "array", "items": STR}, "due_date": DATE,
                "priority": {"type": "integer", "minimum": 1, "maximum": 4, "description": "1 urgent, 2 high, 3 normal, 4 low"},
                "tags": {"type": "array", "items": STR}}, ("list_id", "category", "title")),
             create_task, group="clickup", risk=Risk.MEDIUM,
             summarize=lambda a: f"Create ClickUp task '{build_task_name(a['category'], a['title'], prefixes, settings.clickup_title_format)}'"
                                 + (f" for {', '.join(a['assignees'])}" if a.get("assignees") else "")
                                 + (f" due {a['due_date']}" if a.get("due_date") else "")))

    def update_task(task_id, status=None, name=None, due_date=None, priority=None, add_assignees=None,
                    remove_assignees=None, description=None):
        assignees = None
        if add_assignees or remove_assignees:
            assignees = {"add": I.clickup.resolve_member_ids(add_assignees or []),
                         "rem": I.clickup.resolve_member_ids(remove_assignees or [])}
        return I.clickup.update_task(task_id, status=status, name=name, due_date=_date_ms(due_date), priority=priority,
                                     assignees=assignees, description=description)

    add(Tool("clickup_update_task", "Change a task's status, name, due date, priority, description or assignees.",
             S({"task_id": STR, "status": {"type": "string"}, "name": {"type": "string"}, "due_date": DATE,
                "priority": {"type": "integer", "minimum": 1, "maximum": 4}, "description": {"type": "string"},
                "add_assignees": {"type": "array", "items": STR}, "remove_assignees": {"type": "array", "items": STR}},
               ("task_id",)), update_task, group="clickup", risk=Risk.MEDIUM,
             summarize=lambda a: "Update ClickUp task " + a["task_id"] + ": " +
                                 ", ".join(f"{k}={v}" for k, v in a.items() if k != "task_id")))
    add(Tool("clickup_comment", "Add a comment to a task.", S({"task_id": STR, "text": STR}, ("task_id", "text")),
             lambda task_id, text: I.clickup.add_comment(task_id, text), group="clickup", risk=Risk.MEDIUM,
             summarize=lambda a: f"Comment on ClickUp task {a['task_id']}: \"{a['text'][:120]}\""))

    # ===== Calendar & Drive ==========================================================================
    add(Tool("calendar_events", "Calendar events from now for N days, or for a specific date, optionally matching text.",
             S({"days": {"type": "number", "minimum": 0.1, "maximum": 31}, "date": DATE, "query": {"type": "string"}}),
             lambda days=1, date=None, query=None: I.calendar.upcoming(days, date, query), group="calendar"))
    add(Tool("drive_search", "Search Google Drive files you can access by name or content.",
             S({"query": STR, "max_results": {"type": "integer", "minimum": 1, "maximum": 30}}, ("query",)),
             lambda query, max_results=10: I.drive.search(query, max_results), group="drive"))
    add(Tool("drive_read", "Read the text of a Drive file (Docs, Sheets, Slides, PDF, Office).",
             S({"file_id": STR, "max_chars": {"type": "integer", "minimum": 500, "maximum": 40000}}, ("file_id",)),
             lambda file_id, max_chars=15000: I.drive.read(file_id, max_chars), group="drive", untrusted_output=True))
    add(Tool("drive_download", "Save a Drive file to a local folder (Google Docs become Office files).",
             S({"file_id": STR, "folder": STR}, ("file_id", "folder")),
             lambda file_id, folder: I.drive.download(file_id, folder), group="drive", risk=Risk.MEDIUM,
             summarize=lambda a: f"Download Drive file {a['file_id']} to {a['folder']}"))

    # ===== Workflows ===============================================================================
    add(Tool("daily_briefing_data", "Collect today's calendar, unread important email, configured Slack channels and the "
             "user's ClickUp deadlines in one call. Use for 'daily briefing'.", S({}), lambda: W.daily_briefing(),
             group="workflow", long_running=True, untrusted_output=True))
    add(Tool("meeting_prep_data", "Collect the next meeting (or one matching query) plus related emails with attendees, "
             "Slack discussion, Drive docs and ClickUp status.", S({"query": {"type": "string"}}),
             lambda query=None: W.meeting_prep(query), group="workflow", long_running=True, untrusted_output=True))
    add(Tool("project_status_data", "Collect a project's ClickUp metrics and its Slack channel discussion, with Slack "
             "messages linked to tasks. Use for progress reports and 'what is pending'.",
             S({"project": STR, "since": SINCE}, ("project",)),
             lambda project, since="today": W.project_status(project, since), group="workflow", long_running=True, untrusted_output=True))
    add(Tool("email_slack_crosscheck", "Read an email (by id, or the first match of a Gmail query) and find Slack "
             "discussion about the same issue.", S({"message_id": {"type": "string"}, "query": {"type": "string"}}),
             lambda message_id=None, query=None: W.email_slack_crosscheck(message_id, query), group="workflow",
             long_running=True, untrusted_output=True))

    # ===== Documents ===============================================================================
    add(Tool("save_document", "Save a report/document from Markdown (headings, bullets, **bold**, tables) as docx, pdf or md.",
             S({"title": STR, "content": STR, "folder": {"type": "string"}, "format": {"enum": ["docx", "pdf", "md"]}},
               ("title", "content")),
             lambda title, content, folder=None, format="docx": docs.save_document(title, content,
                                                                                    folder or settings.report_folder, format),
             risk=Risk.MEDIUM, summarize=lambda a: f"Save '{a['title']}' as {a.get('format', 'docx')}"))
    add(Tool("convert_to_pdf", "Convert a Word, PowerPoint or Excel file to PDF using installed Microsoft Office.",
             S({"path": STR}, ("path",)), docs.convert_to_pdf, risk=Risk.MEDIUM,
             summarize=lambda a: f"Convert {a['path']} to PDF"))
    add(Tool("create_spreadsheet", "Create an .xlsx file. sheets maps sheet names to rows (first row = headers).",
             S({"path": STR, "sheets": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "array"}}}},
               ("path", "sheets")), docs.create_spreadsheet, risk=Risk.MEDIUM,
             summarize=lambda a: f"Create spreadsheet {a['path']}"))

    # ===== In-app UI control (Windows UI Automation) ===============================================
    add(Tool("list_controls", "See the buttons, menus, fields and list items in the active window (or a named one). "
             "Use before clicking inside an app.", S({"window": {"type": "string"}, "filter": {"type": "string"}}),
             uia.list_controls))
    add(Tool("click_control", "Click/double-click/right-click a control by name or by index from list_controls.",
             S({"name": {"type": "string"}, "index": {"type": "integer", "minimum": 0}, "window": {"type": "string"},
                "control_type": {"type": "string"}, "action": {"enum": ["click", "double_click", "right_click"]}}),
             uia.click_control, risk=lambda a: uia.control_risk(uia.name_for_risk(a)), trustable=False,
             summarize=lambda a: f"Click '{uia.name_for_risk(a)}' in {km.foreground_title() or 'the active window'}"))
    add(Tool("set_control_text", "Put text into a text field by name/index (or the focused field).",
             S({"text": {"type": "string", "maxLength": 5000}, "name": {"type": "string"},
                "index": {"type": "integer", "minimum": 0}, "window": {"type": "string"}}, ("text",)),
             uia.set_control_text, risk=lambda a: km.typing_risk(a), trustable=False))
    add(Tool("read_window_text", "Read the visible text of the active (or named) window via accessibility — e.g. the "
             "Slack desktop app, WhatsApp, a dialog.", S({"window": {"type": "string"}}), uia.read_window, untrusted_output=True))
    add(Tool("drag_control", "Drag one control onto another (e.g. a file onto a folder).",
             S({"source": STR, "target": STR, "window": {"type": "string"}}, ("source", "target")),
             uia.drag_control, risk=Risk.MEDIUM, summarize=lambda a: f"Drag {a['source']} onto {a['target']}"))
    add(Tool("mouse_click", "Click at the current mouse position (left/right, single/double).",
             S({"button": {"enum": ["left", "right", "middle"]}, "double": {"type": "boolean"}}), uia.mouse_click))

    # ===== Browser agent ===========================================================================
    add(Tool("browser_open", "Open a URL in ROVEN's controllable browser window (Playwright).", S({"url": STR}, ("url",)),
             browser.goto))
    add(Tool("browser_read_page", "Read the current page's text (to summarise articles, compare products, etc.).",
             S({"max_chars": {"type": "integer", "minimum": 1000, "maximum": 40000}}), browser.read, untrusted_output=True))
    add(Tool("browser_links", "List visible links on the page, optionally filtered.", S({"filter": {"type": "string"}}),
             browser.links, untrusted_output=True))
    add(Tool("browser_click", "Click a link/button by its visible text (role: button, link, tab, checkbox...).",
             S({"text": STR, "role": {"type": "string"}, "nth": {"type": "integer", "minimum": 0}}, ("text",)),
             browser.click, risk=ba.click_risk, trustable=False,
             summarize=lambda a: f"Click '{a['text']}' on the web page"))
    add(Tool("browser_fill", "Type a value into a form field by label/placeholder. Never for passwords or payment data.",
             S({"field": STR, "value": {"type": "string", "maxLength": 5000}}, ("field", "value")), browser.fill))
    add(Tool("browser_press", "Press a key in the page (Enter, Tab, Escape, ArrowDown...).", S({"key": STR}, ("key",)),
             browser.press, risk=ba.press_risk, trustable=False, summarize=lambda a: f"Press {a['key']} on the web page"))
    add(Tool("browser_tabs", "List open browser tabs.", S({}), browser.tabs))
    add(Tool("browser_tab_action", "new (optional url), switch/close (index), back, forward, reload.",
             S({"action": {"enum": ["new", "switch", "close", "back", "forward", "reload"]},
                "index": {"type": "integer", "minimum": 0}, "url": {"type": "string"}}, ("action",)), browser.tab_action))
    add(Tool("browser_download", "Click a download link/button and save the file.",
             S({"text": STR, "folder": {"type": "string"}}, ("text",)), browser.download, risk=Risk.MEDIUM,
             summarize=lambda a: f"Download '{a['text']}' to {a.get('folder', '~/Downloads')}"))
    add(Tool("browser_upload", "Attach a local file to a file input on the page.",
             S({"field": STR, "path": STR}, ("field", "path")), browser.upload, risk=Risk.HIGH, trustable=False,
             summarize=lambda a: f"Upload {a['path']} to the web page"))
