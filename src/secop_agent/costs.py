"""Dollar cost of model calls (complements what LangSmith shows).

LangSmith only computes cost when it knows the model's price. To avoid depending on
that, this module counts the tokens of every call (LangChain ``usage_metadata``) and
multiplies them by Anthropic's public prices. Usage::

    counter = CostCounter()
    agent.invoke(inputs, config={"callbacks": [counter]})
    print(counter.summary())
"""
from __future__ import annotations

import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

# USD per million tokens: (input, output, cache write, cache read).
# Anthropic API prices (October 2026). Haiku 5.5: prompts up to 100K tokens.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
}


# Providers whose models run on this machine (e.g. through Ollama): no per-token price.
LOCAL_PROVIDERS = {"ollama"}
KNOWN_PROVIDERS = {"anthropic", "openai", *LOCAL_PROVIDERS}
# Model families served locally by Ollama in this project (response metadata has no provider prefix).
LOCAL_MODEL_PREFIXES = ("qwen", "llama", "mistral", "gemma", "phi")


def model_name(model: str | None) -> str:
    """Strip the provider prefix only: ``'anthropic:claude-haiku-5-5'`` -> ``'claude-haiku-5-5'``,
    ``'ollama:qwen2.5:3b'`` -> ``'qwen2.5:3b'``."""
    text = str(model or "")
    provider, _, rest = text.partition(":")
    return rest if rest and provider in KNOWN_PROVIDERS else text


def is_local_model(model: str | None) -> bool:
    """True for models executed locally (cost is zero, only latency matters)."""
    text = str(model or "")
    return text.partition(":")[0] in LOCAL_PROVIDERS or model_name(text).startswith(LOCAL_MODEL_PREFIXES)


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write: int = 0,
    cache_read: int = 0,
) -> float | None:
    """Cost of one call. ``input_tokens`` includes cache tokens, as in ``usage_metadata``.

    Returns ``0.0`` for local models and ``None`` when the model has no known price.
    """
    if is_local_model(model):
        return 0.0
    price = PRICES.get(model_name(model))
    if price is None:
        return None
    p_in, p_out, p_write, p_read = price
    base = max(0, input_tokens - cache_write - cache_read)
    return (base * p_in + output_tokens * p_out + cache_write * p_write + cache_read * p_read) / 1_000_000


def message_usage(message: Any) -> dict[str, int]:
    """Token usage of a LangChain ``AIMessage`` (zeros when it has no ``usage_metadata``)."""
    usage = getattr(message, "usage_metadata", None) or {}
    details = usage.get("input_token_details") or {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_write": int(details.get("cache_creation") or 0),
        "cache_read": int(details.get("cache_read") or 0),
    }


class CostCounter(BaseCallbackHandler):
    """Callback that accumulates tokens and cost of ALL model calls in a run,
    including the ones tools and memory make internally (summaries, fact extraction)."""

    def __init__(self, default_model: str = "") -> None:
        self.default_model = default_model
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def on_llm_end(self, response, **kwargs: Any) -> None:  # noqa: ANN001 - LangChain signature
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                if message is None:
                    continue
                usage = message_usage(message)
                metadata = getattr(message, "response_metadata", None) or {}
                model = metadata.get("model_name") or metadata.get("model") or self.default_model
                with self._lock:
                    self.calls.append(
                        {**usage, "model": model_name(model), "cost_usd": cost_usd(model, **usage)}
                    )

    def reset(self) -> None:
        with self._lock:
            self.calls.clear()

    def summary(self) -> dict[str, Any]:
        with self._lock:
            calls = list(self.calls)
        costs = [c["cost_usd"] for c in calls]
        return {
            "model_calls": len(calls),
            "input_tokens": sum(c["input_tokens"] for c in calls),
            "output_tokens": sum(c["output_tokens"] for c in calls),
            "cache_read_tokens": sum(c["cache_read"] for c in calls),
            "cost_usd": round(sum(x for x in costs if x is not None), 6) if calls else 0.0,
            "cost_complete": all(x is not None for x in costs),  # False if a model has no price
        }
