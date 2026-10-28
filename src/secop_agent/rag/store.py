"""Persistent, idempotent indexing through the shared embedding foundation."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from chromadb.api.models.Collection import Collection

from secop_agent import embeddings
from secop_agent.config import VECTOR_STORE_DIR
from secop_agent.rag.documents import Chunk, load_corpus

COLLECTION_NAME = "tender_documents"


def get_index_collection(path: Path | str = VECTOR_STORE_DIR) -> Collection:
    """Open the tender collection with the project's cosine embedding model."""
    return embeddings.get_collection(embeddings.get_client(path), COLLECTION_NAME)


def build_index(
    chunks: list[Chunk] | None = None, *, rebuild: bool = False,
    path: Path | str = VECTOR_STORE_DIR,
) -> int:
    """Upsert supplied chunks and return the resulting collection size.

    Rebuild removes stale chunks by deleting the collection first. An ordinary
    upsert deliberately leaves unrelated existing documents in the collection.
    """
    chunks = load_corpus() if chunks is None else chunks
    client = embeddings.get_client(path)
    if rebuild and COLLECTION_NAME in {item.name for item in client.list_collections()}:
        client.delete_collection(COLLECTION_NAME)
    collection = embeddings.get_collection(client, COLLECTION_NAME)
    batch_size = min(256, client.get_max_batch_size())
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        collection.upsert(
            ids=[chunk.chunk_id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            metadatas=[asdict(chunk) for chunk in batch],
        )
    return collection.count()
