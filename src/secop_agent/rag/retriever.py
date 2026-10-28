"""Process-aware semantic retrieval with conservative lexical support checks."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import fields
from typing import Any

from chromadb.api.models.Collection import Collection

from secop_agent.rag.documents import Chunk, RetrievedChunk
from secop_agent.rag.store import get_index_collection

# Question wording and generic document terms must not count as evidence.
_STOP_WORDS = frozenset("""
a al algo ante aquel como con cual cuales cuando cuanto cuantos de del desde dice
documento donde el ella en entre es esa ese esta este estos exige exigen exigido
exigida indica la las le les lo los me menciona mi no o para por proceso procesos
pliego pliegos que quien se segun si sobre son su sus tiene un una unos unas y
numero pdf favor saber necesito informacion requisitos requisito requerido requerida
minima minimo maxima maximo debera debe solicita solicitan establecen establece
cada pide
""".split())

_WORD_FORMS = {
    "cierra": "cierre", "cerrara": "cierre",
    "retiene": "retener", "retendra": "retener", "retencion": "retener",
    "paga": "pago", "pagara": "pago", "pagaderos": "pago",
}


def _normalize(text: str) -> str:
    """Fold accents, punctuation and case for matching identifiers and entities."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _terms(text: str) -> set[str]:
    """Extract lightly stemmed Spanish content words without a new dependency."""
    terms = set()
    for token in _normalize(text.replace("%", " porcentaje ")).split():
        if token in _STOP_WORDS or len(token) < 3 or token.isdigit():
            continue
        token = _WORD_FORMS.get(token, token)
        if len(token) > 5 and token.endswith("es"):
            token = token[:-2]
        elif len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        terms.add(token)
    return terms


def _contains(text: str, phrase: str) -> bool:
    """Match whole normalized phrases, including purely numeric references."""
    return bool(phrase) and f" {phrase} " in f" {text} "


class TenderRetriever:
    """Retrieve cited tender sections, filtering explicit process mentions first.

    The default threshold is calibrated on the checked-in 24-question fixture.
    Scores combine cosine similarity (80%) and query-term coverage (20%), with
    a 0.2 bonus for a query naming an exact section title. At least 60% of
    the content terms must occur in the section; identity
    mentions are removed before scoring so a known process alone is no evidence.
    This is a retrieval gate, not a guarantee that a complete answer exists.
    """

    def __init__(
        self, collection: Collection | None = None, *, min_score: float = 0.40,
        default_k: int = 5,
    ) -> None:
        if not 0 <= min_score <= 1:
            raise ValueError("min_score must be between zero and one")
        if default_k < 1:
            raise ValueError("default_k must be positive")
        self.collection = collection if collection is not None else get_index_collection()
        self.min_score = min_score
        self.default_k = default_k

    def list_documents(self) -> list[dict[str, str]]:
        """Return one identity row per indexed PDF, in filename order."""
        result = self.collection.get(include=["metadatas"])
        documents: dict[str, dict[str, str]] = {}
        for metadata in result["metadatas"] or []:
            source = str(metadata["source_file"])
            documents[source] = {
                "file": source, "reference": str(metadata["reference"]),
                "process_id": str(metadata["process_id"]), "entity": str(metadata["entity"]),
                "type": str(metadata["document_type"]),
            }
        return [documents[source] for source in sorted(documents)]

    def _mentioned_documents(self, query: str, documents: list[dict[str, str]]) -> list[str]:
        """Prefer exact identities, then numbered files, then unambiguous entities."""
        normalized = _normalize(query)
        exact = [doc["file"] for doc in documents if any(
            _contains(normalized, _normalize(doc[key])) for key in ("file", "reference", "process_id")
        )]
        if exact:
            return exact
        numbers = re.findall(r"\b(?:proceso|pliego|archivo|documento)\s+(?:numero\s+)?0*(\d+)\b", normalized)
        if numbers:
            return [doc["file"] for doc in documents if str(int(doc["file"].split("_", 1)[0])) in numbers]
        matches: list[tuple[int, str]] = []
        for doc in documents:
            aliases = [doc["entity"], *re.findall(r"\(([^)]+)\)", doc["entity"])]
            for alias in aliases:
                if _contains(normalized, _normalize(alias)):
                    matches.append((len(_normalize(alias)), doc["file"]))
        if not matches:
            return []
        longest = max(length for length, _ in matches)
        return sorted({source for length, source in matches if length == longest})

    def detect_process(self, query: str) -> str | None:
        """Resolve a unique indexed file; ambiguous entity names return None."""
        matches = self._mentioned_documents(query, self.list_documents())
        return matches[0] if len(matches) == 1 else None

    def _content_query(self, query: str, documents: list[dict[str, str]]) -> str:
        """Remove process identity tokens so they cannot raise relevance scores."""
        query = _normalize(query)
        for doc in documents:
            for key in ("file", "reference", "process_id", "entity"):
                value = _normalize(doc[key])
                query = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", " ", query)
            for acronym in re.findall(r"\(([^)]+)\)", doc["entity"]):
                query = re.sub(rf"\b{re.escape(_normalize(acronym))}\b", " ", query)
        return re.sub(r"\b(?:proceso|pliego|archivo|documento)\s+(?:numero\s+)?\d+\b", " ", query).strip()

    def search(
        self, query: str, k: int | None = None, *, source_file: str | None = None,
        reference: str | None = None,
    ) -> list[RetrievedChunk]:
        """Return supported sections, or [] for absent/irrelevant source content."""
        limit = self.default_k if k is None else k
        if limit < 1 or not query.strip() or self.collection.count() == 0:
            return []
        documents = self.list_documents()
        mentioned = self._mentioned_documents(query, documents)
        if not mentioned and re.search(
            r"\b(?:proceso|pliego|archivo|documento)\s+(?:numero\s+)?\d+\b|\bco1\s+req\s+\d+",
            _normalize(query),
        ):
            return []
        filters: list[dict[str, Any]] = []
        if source_file is not None:
            filters.append({"source_file": source_file})
        if reference is not None:
            matching = [doc["reference"] for doc in documents if _normalize(doc["reference"]) == _normalize(reference)]
            if not matching:
                return []
            filters.append({"reference": matching[0]})
        if mentioned:
            filters.append({"source_file": {"$in": mentioned}})
        where = {"$and": filters} if len(filters) > 1 else filters[0] if filters else None
        content_query = self._content_query(query, documents)
        query_terms = _terms(content_query)
        if not query_terms:
            return []
        result = self.collection.query(
            query_texts=[content_query], n_results=min(self.collection.count(), max(30, limit * 6)),
            where=where, include=["metadatas", "documents", "distances"],
        )
        hits: list[RetrievedChunk] = []
        names = {field.name for field in fields(Chunk)}
        for metadata, text, distance in zip(
            (result["metadatas"] or [[]])[0], (result["documents"] or [[]])[0],
            (result["distances"] or [[]])[0], strict=True,
        ):
            chunk = Chunk(**{name: metadata[name] for name in names})
            # Drop the identity prefix, retaining the section title as evidence.
            evidence = chunk.section + "\n" + (text or "").partition("\n")[2]
            coverage = len(query_terms & _terms(evidence)) / len(query_terms)
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            title = re.sub(r"^\d+\.\s*", "", chunk.section)
            title_bonus = 0.2 if _normalize(content_query) == _normalize(title) else 0.0
            score = min(1.0, 0.8 * similarity + 0.2 * coverage + title_bonus)
            if coverage >= 0.6 and score >= self.min_score:
                hits.append(RetrievedChunk(chunk=chunk, distance=float(distance), score=score))
        return sorted(hits, key=lambda hit: (-hit.score, hit.chunk.chunk_id))[:limit]
