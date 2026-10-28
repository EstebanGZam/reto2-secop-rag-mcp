"""Single entry point for creating chat models.

Keeping model construction in one place lets us switch providers by changing the
`MODELO` environment variable only. Sampling parameters (temperature, top_p, top_k)
are deliberately never passed: Claude Haiku 5.5 rejects them with HTTP 400.
"""
from __future__ import annotations

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from secop_agent.config import get_settings


@lru_cache(maxsize=8)
def get_chat_model(model: str | None = None, max_tokens: int = 1024) -> BaseChatModel:
    """Return a cached chat model, e.g. ``get_chat_model("anthropic:claude-haiku-5-5")``."""
    return init_chat_model(model or get_settings().chat_model, max_tokens=max_tokens)


def message_text(message) -> str:
    """Extract plain text from a LangChain message whose content may be a list of blocks."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        else:
            parts.append(str(block))
    return "".join(parts)
