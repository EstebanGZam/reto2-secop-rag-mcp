"""Pure provenance tests; no credentials, models or database required."""
import pytest

from secop_agent.grounding import ABSTENTION, guard_answer, parse_citations

TAG = "[fuente: tender.pdf, p. 2, §5 Finance]"


def test_parse_unique_complete_tags():
    assert parse_citations(f"Dato {TAG}. Otro {TAG} [fuente: memoria]") == [TAG, "[fuente: memoria]"]
    assert parse_citations("[fuente: incomplete") == []


@pytest.mark.parametrize("answer,sources,options,expected", [
    (f"Liquidez 1.6 {TAG}", [TAG], {"retrieval_found": True}, True),
    (f"Liquidez 1.6 {TAG}", [], {"retrieval_found": True}, False),
    ("Sin cita", [TAG], {"retrieval_found": True}, False),
    (f"Dato {TAG}", [TAG], {}, False),
    ("Dato [fuente: company.json]", ["company.json"], {"other_evidence": True}, True),
    ("Dato [fuente: memoria]", [], {"memory_available": True}, True),
    ("Dato [fuente: memoria]", [], {}, False),
    (f"Dato {TAG} [fuente: invented]", [TAG], {"retrieval_found": True}, False),
    ("Dato [fuente: tender.pdf, p. 9, §5 Finance]", [TAG], {"retrieval_found": True}, False),
])
def test_guard_provenance(answer, sources, options, expected):
    final, citations, abstained = guard_answer(answer, sources, **options)
    assert final == (answer if expected else ABSTENTION)
    assert abstained is not expected
    assert bool(citations) is expected


def test_preserve_existing_abstention():
    answer = "No lo sé: el correo no está disponible."
    assert guard_answer(answer, []) == (answer, [], True)
