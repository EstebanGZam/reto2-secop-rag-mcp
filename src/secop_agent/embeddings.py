"""Shared embedding function and Chroma helpers.

The tender-document index and the long/mid-term memory use the SAME embedding model:
vectors from different models are not comparable, so it is defined only here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from secop_agent.config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embedding_function():
    """Multilingual sentence-transformers model (works well with Spanish text)."""
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def get_client(path: Path | str) -> chromadb.ClientAPI:
    """Open (or create) a persistent Chroma database at ``path``."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def get_collection(client: chromadb.ClientAPI, name: str, embedding_function=None):
    """Return a collection that measures similarity with cosine distance (0 = identical, 2 = opposite)."""
    return client.get_or_create_collection(
        name=name,
        embedding_function=embedding_function or get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )
