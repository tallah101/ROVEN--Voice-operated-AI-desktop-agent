"""Risk-tiered permission model.

LOW    -> runs automatically.
MEDIUM -> asks, unless the user has marked that tool as trusted.
HIGH   -> always asks (shutdown, recycle-bin, typing into terminals ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable


class Risk(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


@dataclass
class Decision:
    allowed: bool
    reason: str


class PermissionManager:
    def __init__(self, settings, confirm: Callable[[str], bool] | None = None) -> None:
        self.settings = settings
        self.confirm = confirm

    def decide(self, tool_name: str, risk: Risk, trustable: bool, summary: str) -> Decision:
        if risk == Risk.LOW:
            return Decision(True, "low risk")
        if risk == Risk.MEDIUM and trustable and tool_name in self.settings.trusted_actions:
            return Decision(True, "trusted by user")
        if self.confirm is None:
            return Decision(False, "confirmation required but no way to ask the user")
        if self.confirm(summary):
            return Decision(True, "confirmed by user")
        return Decision(False, "the user declined or did not confirm")
