"""Short-term memory: a sliding window over the current conversation.

Also defines the primitives shared by every memory level: the message shape,
the injectable LLM signature and the transcript formatter used in prompts.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

Message = dict[str, str]  # {"role": "user" | "assistant", "content": "..."}
LLMCallable = Callable[[str, list[Message]], str]  # (system_prompt, messages) -> text

ROLE_LABELS = {"user": "Usuario", "assistant": "Asistente"}


def format_transcript(messages: Iterable[Message]) -> str:
    """Render messages as ``Usuario: ...`` / ``Asistente: ...`` lines for a prompt."""
    return "\n".join(
        f"{ROLE_LABELS.get(m['role'], m['role'])}: {m['content'].strip()}" for m in messages
    )


class ShortTermMemory:
    """Last messages of the session, bounded by message count and total characters.

    When a limit is exceeded the oldest user+assistant pair is evicted (so the window
    never starts with an orphan answer) and returned to the caller, which hands it to
    the mid-term memory. The last exchange is always kept, even if it alone exceeds
    ``max_chars``.
    """

    MIN_KEPT = 2  # one user+assistant exchange

    def __init__(self, max_messages: int = 10, max_chars: int = 8000) -> None:
        if max_messages < self.MIN_KEPT:
            raise ValueError(f"max_messages must be >= {self.MIN_KEPT}")
        self.max_messages = max_messages
        self.max_chars = max_chars
        self._messages: list[Message] = []

    @property
    def messages(self) -> list[Message]:
        """Copy of the messages currently in the window (oldest first)."""
        return [dict(m) for m in self._messages]

    def __len__(self) -> int:
        return len(self._messages)

    def total_chars(self) -> int:
        """Total number of content characters in the window."""
        return sum(len(m["content"]) for m in self._messages)

    def add(self, role: str, content: str) -> list[Message]:
        """Append a message and return the messages evicted to respect the limits."""
        self._messages.append({"role": role, "content": content})
        evicted: list[Message] = []
        while self._over_limit():
            size = self._oldest_unit_size()
            if len(self._messages) - size < self.MIN_KEPT:
                break
            evicted.extend(self._messages[:size])
            del self._messages[:size]
        return evicted

    def drain(self) -> list[Message]:
        """Remove and return every message in the window (used when a session closes)."""
        remaining, self._messages = self._messages, []
        return remaining

    def _over_limit(self) -> bool:
        return len(self._messages) > self.max_messages or self.total_chars() > self.max_chars

    def _oldest_unit_size(self) -> int:
        """2 when the window starts with a user+assistant pair, otherwise 1."""
        first_two = [m["role"] for m in self._messages[:2]]
        return 2 if first_two == ["user", "assistant"] else 1
