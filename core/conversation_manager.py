"""Short-term conversation context so follow-ups ("make it shorter", "was it fixed?") just work."""
from __future__ import annotations

import time


class ConversationManager:
    def __init__(self, max_messages: int = 40, idle_reset_seconds: float = 900) -> None:
        self.max_messages = max_messages
        self.idle_reset_seconds = idle_reset_seconds
        self._messages: list[dict] = []
        self._last = time.time()

    def reset(self) -> None:
        self._messages.clear()

    def _touch(self) -> None:
        if time.time() - self._last > self.idle_reset_seconds:
            self.reset()
        self._last = time.time()

    def add_user_text(self, text: str) -> None:
        self._touch()
        block = {"type": "text", "text": text}
        if self._messages and self._messages[-1]["role"] == "user":
            self._messages[-1]["content"].append(block)
        else:
            self._messages.append({"role": "user", "content": [block]})
        self._trim()

    def add_assistant(self, blocks: list[dict]) -> None:
        self._messages.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})

    def add_tool_results(self, results: list[dict], keep_images: int = 2) -> None:
        self._messages.append({"role": "user", "content": results})
        self._prune_images(keep_images)

    def _prune_images(self, keep: int) -> None:
        """Screenshots are large; keep only the newest few in context."""
        seen = 0
        for msg in reversed(self._messages):
            for block in msg["content"]:
                if block.get("type") != "tool_result" or not isinstance(block.get("content"), list):
                    continue
                if any(b.get("type") == "image" for b in block["content"]):
                    seen += 1
                    if seen > keep:
                        block["content"] = [b if b.get("type") != "image" else
                                            {"type": "text", "text": "[older screenshot removed]"} for b in block["content"]]

    def messages(self) -> list[dict]:
        return list(self._messages)

    @staticmethod
    def _is_turn_start(msg: dict) -> bool:
        return msg["role"] == "user" and all(b.get("type") == "text" for b in msg["content"])

    def _trim(self) -> None:
        # Only cut at the start of a user turn so tool_use / tool_result pairs stay intact.
        while len(self._messages) > self.max_messages:
            cut = next((i for i in range(1, len(self._messages)) if self._is_turn_start(self._messages[i])), None)
            if cut is None:
                break
            del self._messages[:cut]
