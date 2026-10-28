"""Central configuration: project paths and environment-driven settings.

Every module reads paths and settings from here so that the notebook, the CLI
scripts, the tests and the MCP server all agree on where data lives.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "datos"
TENDER_DOCS_DIR = DATA_DIR / "pliegos"
RESULTS_DIR = PROJECT_ROOT / "resultados"
DATASETS_DIR = PROJECT_ROOT / "datasets"

# Persistent stores (git-ignored). Both are plain folders so they survive between sessions.
VECTOR_STORE_DIR = PROJECT_ROOT / "almacen" / "chroma"
MEMORY_STORE_DIR = PROJECT_ROOT / "memoria" / "chroma"

# Multilingual sentence-transformers model recommended by the course RAG tutorial.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_CHAT_MODEL = "anthropic:claude-haiku-5-5"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables (or `.env`)."""

    chat_model: str = field(default_factory=lambda: os.getenv("MODELO", DEFAULT_CHAT_MODEL))
    data_mode: str = field(default_factory=lambda: os.getenv("MODO_DATOS", "muestra"))
    langsmith_project: str = field(
        default_factory=lambda: os.getenv("LANGSMITH_PROJECT", "secop-reto2-rag-mcp")
    )

    @property
    def has_llm_credentials(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY"))

    @property
    def tracing_enabled(self) -> bool:
        return bool(os.getenv("LANGSMITH_API_KEY")) and os.getenv("LANGSMITH_TRACING", "").lower() == "true"


def get_settings() -> Settings:
    return Settings()
