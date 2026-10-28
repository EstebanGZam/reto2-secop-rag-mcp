"""Offline parsing, persistent-index and source/section retrieval acceptance tests."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from pypdf import PdfWriter

from secop_agent.config import DATASETS_DIR
from secop_agent.extraction import _requirement_context
from secop_agent.rag import (
    RetrievedChunk, TenderRetriever, build_index, get_index_collection,
    load_corpus, load_tender_document,
)
from secop_agent.rag.documents import Chunk, _split_section


@pytest.fixture(scope="module")
def corpus() -> list[Chunk]:
    """Read the actual twenty PDFs, without accessing any model service."""
    return load_corpus()


@pytest.fixture(scope="module")
def indexed(corpus: list[Chunk], tmp_path_factory: pytest.TempPathFactory):
    """Use real cached multilingual embeddings and a temporary persistent index."""
    path = tmp_path_factory.mktemp("tender-index")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HF_HUB_OFFLINE", "1")
        build_index(corpus, path=path)
        yield path, TenderRetriever(get_index_collection(path))


def test_parse_all_documents_and_metadata(corpus: list[Chunk]) -> None:
    """All sections retain complete identity and clean source text."""
    assert len({chunk.source_file for chunk in corpus}) == 20
    assert len(corpus) == 157
    assert len({chunk.chunk_id for chunk in corpus}) == len(corpus)
    for chunk in corpus:
        assert chunk.page in (1, 2)
        assert re.fullmatch(r"CO1\.REQ\.\d+", chunk.process_id)
        assert chunk.reference and chunk.entity and chunk.document_type
        assert re.match(r"^\d+\. ", chunk.section)
        assert chunk.text.startswith(f"{chunk.reference} · {chunk.entity} · {chunk.section}\n")
        assert "simulado con fines educativos" not in chunk.text.lower()
        assert "ficticios" not in chunk.text
        assert "Página " not in chunk.text
    assert corpus == load_corpus()


def test_section_continuation_and_citation(corpus: list[Chunk]) -> None:
    """Sections crossing pages keep their start page and all continuation text."""
    invitation = next(c for c in corpus if c.chunk_id == "03_RE_CGBM_049_2024.pdf#s05#0")
    assert invitation.page == 1
    assert "no se verifica capacidad financiera" in invitation.text
    finance = next(c for c in corpus if c.chunk_id == "11_FDLS_LP_098_2019.pdf#s05#0")
    assert finance.page == 2
    assert "Mayor o igual a 1.6" in finance.text
    assert RetrievedChunk(finance, 0.3, 0.7).citation() == (
        "[fuente: 11_FDLS_LP_098_2019.pdf, p. 2, §5 Capacidad financiera y organizacional (según RUP)]"
    )
    payment = next(c for c in corpus if c.chunk_id == "16_CD_PS_GDCH_186SS_2024.pdf#s06#0")
    assert payment.page == 1
    assert "10 cuotas mensuales" in " ".join(payment.text.split())


def test_long_section_splits_without_lost_words() -> None:
    """Long section fragments remain bounded, overlapping and deterministic."""
    content = " ".join(f"word{index:04d}" for index in range(600))
    pieces = _split_section(content)
    assert len(pieces) > 1
    assert all(len(text) <= 1200 for _, text in pieces)
    assert set(content.split()) == {word for _, text in pieces for word in text.split()}
    assert set(pieces[0][1].split()) & set(pieces[1][1].split())
    assert pieces == _split_section(content)
    long_token = "x" * 5000
    assert "".join(text for _, text in _split_section(long_token)) == long_token
    with pytest.raises(ValueError):
        _split_section(content, size=100, overlap=100)


def test_invalid_document_and_missing_directory(tmp_path: Path) -> None:
    """An unreadable tender identity cannot silently become an empty index."""
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    with pytest.raises(ValueError, match="Missing tender identity"):
        load_tender_document(path)
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "missing")


def test_index_upsert_persistence_and_rebuild(indexed, corpus: list[Chunk]) -> None:
    """Upserts do not duplicate chunks and a rebuild removes obsolete records."""
    path, retriever = indexed
    assert build_index(corpus, path=path) == len(corpus)
    collection = get_index_collection(path)
    stored = collection.get(ids=[corpus[0].chunk_id], include=["metadatas", "documents"])
    assert stored["metadatas"][0] == asdict(corpus[0])
    assert stored["documents"][0] == corpus[0].text
    stale = replace(corpus[0], chunk_id="obsolete-fragment")
    assert build_index([stale], path=path) == len(corpus) + 1
    assert build_index(corpus, rebuild=True, path=path) == len(corpus)
    # The old handle refers to a deleted collection; reopen after a rebuild.
    retriever.collection = get_index_collection(path)
    assert not retriever.collection.get(ids=[stale.chunk_id])["ids"]


@pytest.mark.parametrize(("mention", "prefix"), [
    ("fdls-lp-098-2019", "11_"), ("CO1.REQ.848621", "11_"),
    ("11_FDLS_LP_098_2019.pdf", "11_"), ("proceso 11", "11_"),
    ("pliego 011", "11_"), ("ALCALDIA LOCAL DE SUMAPAZ", "11_"),
    ("gobernacion del choco", "16_"), ("AGROSAVIA", "07_"),
])
def test_detect_process(indexed, mention: str, prefix: str) -> None:
    """Accent/case folding and identity alternatives resolve the same PDF."""
    _, retriever = indexed
    assert retriever.detect_process(mention).startswith(prefix)


def test_filters_and_unknown_processes(indexed) -> None:
    """Explicit filters combine safely and missing identities do not broaden search."""
    _, retriever = indexed
    documents = retriever.list_documents()
    assert len(documents) == 20
    assert set(documents[0]) == {"file", "reference", "process_id", "entity", "type"}
    assert retriever.detect_process("INVIAS") is None
    assert retriever.search("presupuesto oficial del proceso 99") == []
    assert retriever.search("presupuesto de CO1.REQ.999999999") == []
    assert retriever.search("presupuesto", source_file="missing.pdf") == []
    assert retriever.search("presupuesto", reference="missing") == []
    assert retriever.search("liquidez", source_file="11_FDLS_LP_098_2019.pdf", reference="SA-004-2023") == []
    hits = retriever.search("índice de liquidez", reference="fdls-lp-098-2019")
    assert hits and all(hit.chunk.reference == "FDLS-LP-098-2019" for hit in hits)
    assert retriever.search("", k=5) == []
    assert retriever.search("liquidez", k=0) == []
    assert retriever.search("proceso 11") == []
    strict = TenderRetriever(retriever.collection, min_score=1.0)
    assert strict.search("índice de liquidez del proceso 11") == []


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def test_question_fixture_facts_are_present(corpus: list[Chunk]) -> None:
    """Every answer fixture is a literal fact in its indicated PDF section."""
    questions = json.loads((DATASETS_DIR / "tender_questions.json").read_text(encoding="utf-8"))
    assert len(questions) == 24
    assert sum(row["answerable"] for row in questions) == 16
    assert len({row["id"] for row in questions}) == 24
    for row in questions:
        if row["answerable"]:
            matching = [c for c in corpus if c.source_file in row["expected_sources"] and c.section == row["expected_section"]]
            assert matching, row["id"]
            assert _squash(row["expected_answer"]) in _squash(" ".join(c.text for c in matching)), row["id"]
        else:
            assert row["expected_answer"] == "No lo sé"
            assert row["expected_sources"] == []


def test_retrieval_evaluation(indexed, record_property) -> None:
    """Acceptance: source hit@5 >= .9, supporting sections and OOC abstention."""
    _, retriever = indexed
    questions = json.loads((DATASETS_DIR / "tender_questions.json").read_text(encoding="utf-8"))
    source_hits = section_hits = answerable = unanswerable = empty = 0
    failures = []
    for row in questions:
        hits = retriever.search(row["question"], k=5)
        if row["answerable"]:
            answerable += 1
            source_hits += any(hit.chunk.source_file in row["expected_sources"] for hit in hits)
            section_hits += any(hit.chunk.source_file in row["expected_sources"] and hit.chunk.section == row["expected_section"] for hit in hits)
        else:
            unanswerable += 1
            empty += not hits
            if hits:
                failures.append(row["id"])
    record_property("source_hit_at_5", source_hits / answerable)
    record_property("section_hit_at_5", section_hits / answerable)
    record_property("unanswerable_empty_rate", empty / unanswerable)
    print(f"source hit@5={source_hits}/{answerable}; section hit@5={section_hits}/{answerable}; empty={empty}/{unanswerable}")
    assert source_hits / answerable >= 0.9
    assert section_hits / answerable >= 0.9
    assert empty == unanswerable, failures


def test_empty_collection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty index abstains and never requests embeddings for a query."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert build_index([], rebuild=True, path=tmp_path) == 0
    retriever = TenderRetriever(get_index_collection(tmp_path))
    assert retriever.list_documents() == []
    assert retriever.search("presupuesto oficial") == []


def test_real_extraction_context_includes_required_sections(indexed, corpus: list[Chunk]) -> None:
    """Actual retrieval must supply general, object and available requirement sections."""
    _, retriever = indexed
    for document in retriever.list_documents():
        source = document["file"]
        context = _requirement_context(source, retriever)
        required = [chunk for chunk in corpus if chunk.source_file == source and (
            chunk.section.startswith(("1. ", "2. "))
            or any(label in chunk.section for label in (
                "Capacidad financiera", "Experiencia del proponente", "Requisitos habilitantes",
                "Perfil e idoneidad",
            ))
        )]
        for chunk in required:
            # General legal requirements have no bearing on the 14 extracted fields.
            if "jurídicos" not in chunk.section:
                assert chunk.text in context, (source, chunk.section)


@pytest.mark.parametrize("question", [
    "¿Cuál es el salario del gerente del proceso 11?",
    "¿Qué exige sobre ciberseguridad el proceso 11?",
    "¿Qué tiene que ver el seguro del gerente con la liquidez del proceso 11?",
])
def test_additional_unsupported_attributes_abstain(indexed, question: str) -> None:
    """Known process and financial vocabulary cannot support absent attributes."""
    _, retriever = indexed
    assert retriever.search(question) == []


def test_schedule_paraphrase(indexed) -> None:
    """A common conjugated question still finds the schedule section."""
    _, retriever = indexed
    hits = retriever.search("¿Cuándo cierra el proceso 3?")
    assert any(hit.chunk.section == "4. Cronograma" for hit in hits)
