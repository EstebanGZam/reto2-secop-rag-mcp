"""Deterministic citation provenance checks, without a language model."""
from __future__ import annotations

import re
from collections.abc import Iterable

ABSTENTION = "No lo sé: no encontré esa información en los documentos disponibles."
CITATION_PATTERN = re.compile(r"\[fuente: ([^\]\n]+)\]")


def parse_citations(answer: str) -> list[str]:
    """Return unique complete citation tags, preserving their order."""
    return list(dict.fromkeys(match.group(0) for match in CITATION_PATTERN.finditer(answer)))


def is_abstention(answer: str) -> bool:
    """Recognize the required Spanish abstention prefix."""
    return answer.lstrip().casefold().startswith("no lo sé")


def guard_answer(
    answer: str,
    sources: Iterable[str],
    *,
    retrieval_found: bool = False,
    other_evidence: bool = False,
    memory_available: bool = False,
) -> tuple[str, list[str], bool]:
    """Accept only exact citations from this turn's explicit evidence fields.

    Sources may be full document citation tags or plain MCP source strings.
    This checks provenance, not whether each assertion follows from the source.
    An existing abstention is preserved verbatim.
    """
    allowed = {source if source.startswith("[fuente: ") else f"[fuente: {source}]" for source in sources}
    if memory_available:
        allowed.add("[fuente: memoria]")
    cited = parse_citations(answer)
    valid = [tag for tag in cited if tag in allowed]
    if is_abstention(answer):
        return answer, valid, True
    evidence = retrieval_found or other_evidence or memory_available
    if not evidence or not valid or any(tag not in allowed for tag in cited):
        return ABSTENTION, [], True
    return answer, valid, False
