"""Allowlisted tool registry. The model can only call tools registered here, with validated arguments,
after a permission decision. Every call is audited, and repeated side effects need fresh confirmation."""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from security.action_validator import validate_args
from security.permission_manager import Risk

log = logging.getLogger(__name__)
MAX_RESULT_CHARS = 14000


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., Any]
    risk: Risk | Callable[[dict], Risk] = Risk.LOW
    trustable: bool = True
    summarize: Callable[[dict], str] | None = None
    group: str | None = None          # integration group; tool is offered only when that group is connected
    long_running: bool = False        # ROVEN announces "working on it" before running
    trust_listed: bool = False        # dynamic-risk tool that may still be marked trusted (e.g. internal Slack posts)
    untrusted_output: bool = False    # returns outside content (web, email, chat); later scripts need confirmation
    precheck: Callable[[dict], Any] | None = None   # raises to refuse outright (never even asks the user)

    def risk_for(self, args: dict) -> Risk:
        if not callable(self.risk):
            return self.risk
        try:
            return self.risk(args)
        except Exception:
            log.exception("Risk check failed for %s; treating as HIGH", self.name)
            return Risk.HIGH

    def describe(self, args: dict) -> str:
        if self.summarize:
            try:
                return self.summarize(args)
            except Exception:
                pass
        shown = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
        return f"{self.name}({shown})"


@dataclass
class ToolImage:
    """A tool output that includes a picture (e.g. a screenshot) for the AI to look at."""
    data: bytes
    media_type: str
    text: str


@dataclass
class ToolResult:
    ok: bool
    content: str | list        # list = content blocks (image + text)
    text: str = ""             # plain-text version for logs

    def __post_init__(self):
        if not self.text:
            self.text = self.content if isinstance(self.content, str) else ""


class ToolRegistry:
    def __init__(self, permissions, audit, duplicate_window: float = 600, clock: Callable[[], float] = time.time) -> None:
        self.permissions = permissions
        self.audit = audit
        self.duplicate_window = duplicate_window
        self.clock = clock
        self._tools: dict[str, Tool] = {}
        self._effects: dict[str, float] = {}
        self.tainted = False          # True once this request has read outside content
        self.observers: list = []     # callables(name, summary, ok, status_text) e.g. the daily conversation log

    def begin_request(self) -> None:
        self.tainted = False

    def taint(self) -> None:
        self.tainted = True

    def _notify(self, name: str, summary: str, ok: bool, status: str) -> None:
        for obs in self.observers:
            try:
                obs(name, summary, ok, status)
            except Exception:
                log.debug("observer failed", exc_info=True)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def trustable_medium_tools(self) -> list[str]:
        return sorted(t.name for t in self._tools.values()
                      if t.trustable and (t.trust_listed or (not callable(t.risk) and t.risk == Risk.MEDIUM)))

    def schemas(self, groups: set[str] | None = None) -> list[dict]:
        return [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in self._tools.values()
                if t.group is None or groups is None or t.group in groups]

    def describe(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        return tool.describe(args if isinstance(args, dict) else {}) if tool else name

    def execute(self, name: str, args, cancel: threading.Event | None = None) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            self.audit.record("tool_rejected", name, args, "unknown_tool")
            return ToolResult(False, f"Unknown tool '{name}'. Only registered tools can be used.")
        errors = validate_args(tool.parameters, args)
        if errors:
            self.audit.record("tool_rejected", name, args, "invalid_args", errors)
            return ToolResult(False, "Invalid arguments: " + "; ".join(errors))
        if cancel is not None and cancel.is_set():
            return ToolResult(False, "Cancelled by emergency stop. Nothing was done.")
        if tool.precheck is not None:
            try:
                tool.precheck(args)
            except Exception as exc:
                self.audit.record("tool_refused", name, args, "precheck", str(exc))
                self._notify(name, tool.describe(args), False, f"refused: {exc}")
                return ToolResult(False, f"Refused: {exc} Explain this to the user; do not try to work around it.")
        risk = tool.risk_for(args)
        summary = tool.describe(args)
        effect_key = None
        if risk >= Risk.MEDIUM:
            effect_key = name + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
            done_at = self._effects.get(effect_key)
            if done_at is not None and self.clock() - done_at < self.duplicate_window:
                risk = Risk.HIGH
                summary = f"Repeat an action already done at {time.strftime('%H:%M', time.localtime(done_at))}: {summary}"
        decision = self.permissions.decide(name, risk, tool.trustable, summary)
        if not decision.allowed:
            self.audit.record("tool_denied", name, args, risk.name, decision.reason)
            self._notify(name, summary, False, f"not done ({decision.reason})")
            return ToolResult(False, f"Not performed: {decision.reason}. Do not tell the user it was done.")
        try:
            out = tool.func(**args)
        except Exception as exc:  # failures go back to the model; never hidden
            log.exception("Tool %s failed", name)
            self.audit.record("tool_error", name, args, risk.name, repr(exc))
            self._notify(name, summary, False, f"failed: {exc}")
            return ToolResult(False, f"Error: {exc}")
        if tool.untrusted_output:
            self.taint()
        if isinstance(out, ToolImage):
            blocks = [{"type": "image", "source": {"type": "base64", "media_type": out.media_type,
                                                   "data": base64.b64encode(out.data).decode()}},
                      {"type": "text", "text": out.text}]
            self.audit.record("tool_executed", name, args, risk.name, out.text[:500])
            self._notify(name, summary, True, "done")
            return ToolResult(True, blocks, out.text)
        content = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)
        if len(content) > MAX_RESULT_CHARS:
            content = content[:MAX_RESULT_CHARS] + " …[truncated]"
        ok = not (isinstance(out, dict) and out.get("ok") is False)
        if ok and effect_key:
            self._effects[effect_key] = self.clock()
        self.audit.record("tool_executed", name, args, risk.name, content[:500])
        self._notify(name, summary, ok, "done" if ok else "failed")
        return ToolResult(ok, content)
