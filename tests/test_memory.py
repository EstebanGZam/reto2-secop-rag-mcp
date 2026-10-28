"""Tests for the three-level memory. They use a fake LLM (no API key) and real local embeddings."""
from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import json
from datetime import UTC, datetime, timedelta

import pytest

from secop_agent.embeddings import get_client, get_collection, get_embedding_function
from secop_agent.memory import LongTermMemory, MemoryManager, MidTermMemory, ShortTermMemory
from secop_agent.memory.long_term import EXTRACTION_SYSTEM_PROMPT, parse_facts, recall_score
from secop_agent.memory.manager import CONTEXT_NOTE, CURRENT_HEADING, FACTS_HEADING, SESSIONS_HEADING
from secop_agent.memory.mid_term import SUMMARY_SYSTEM_PROMPT

FACT_COMPANY = "El usuario trabaja en una empresa constructora de Bogotá"
FACT_PREFERENCE = "El usuario prefiere respuestas breves con citas de la fuente"


class FakeLLM:
    """Deterministic stand-in for the chat model: summarises by echoing, extracts canned facts."""

    def __init__(self, facts_reply: str = "[]") -> None:
        self.facts_reply = facts_reply
        self.calls: list[tuple[str, list[dict]]] = []
        self.summaries = 0

    def __call__(self, system_prompt: str, messages: list[dict]) -> str:
        self.calls.append((system_prompt, messages))
        if system_prompt == SUMMARY_SYSTEM_PROMPT:
            self.summaries += 1
            new_part = messages[-1]["content"].split("<new_messages>")[1]
            topics = [line.split(":", 1)[1].strip() for line in new_part.splitlines() if line.startswith("Usuario:")]
            return f"Resumen #{self.summaries}: el usuario preguntó por {'; '.join(topics)}."
        if system_prompt == EXTRACTION_SYSTEM_PROMPT:
            return self.facts_reply
        raise AssertionError("unexpected prompt")

    def prompts(self, system_prompt: str) -> list[str]:
        return [messages[-1]["content"] for prompt, messages in self.calls if prompt == system_prompt]


def facts_json(*facts: tuple[str, int]) -> str:
    return json.dumps([{"fact": fact, "importance": importance} for fact, importance in facts], ensure_ascii=False)


@pytest.fixture(scope="session")
def embedding_function():
    return get_embedding_function()


@pytest.fixture
def collections(tmp_path, embedding_function):
    client = get_client(tmp_path / "memory")
    return {
        name: get_collection(client, name, embedding_function) for name in ("sessions", "facts")
    }


def make_manager(store_dir, llm, embedding_function, **kwargs) -> MemoryManager:
    return MemoryManager(store_dir, llm=llm, embedding_function=embedding_function, **kwargs)


# --- short term -----------------------------------------------------------------------------


def test_short_term_evicts_oldest_user_assistant_pairs():
    memory = ShortTermMemory(max_messages=4, max_chars=10_000)
    evicted = []
    for i in range(3):
        evicted += memory.add("user", f"pregunta {i}")
        evicted += memory.add("assistant", f"respuesta {i}")

    assert [m["content"] for m in evicted] == ["pregunta 0", "respuesta 0"]
    assert [m["role"] for m in memory.messages] == ["user", "assistant", "user", "assistant"]
    assert memory.messages[0]["content"] == "pregunta 1"


def test_short_term_char_limit_keeps_last_exchange_and_drain_empties():
    memory = ShortTermMemory(max_messages=10, max_chars=50)
    memory.add("user", "a" * 20)
    memory.add("assistant", "b" * 20)
    memory.add("user", "c" * 40)
    evicted = memory.add("assistant", "d" * 40)  # the last exchange alone exceeds max_chars

    assert [m["content"][0] for m in evicted] == ["a", "b"]
    assert len(memory) == 2
    assert [m["content"][0] for m in memory.drain()] == ["c", "d"]
    assert len(memory) == 0


# --- mid term -------------------------------------------------------------------------------


def test_mid_term_summary_is_progressive(collections):
    llm = FakeLLM()
    memory = MidTermMemory(collections["sessions"], llm)
    memory.absorb([{"role": "user", "content": "el proceso FDLS-LP-098-2019"}, {"role": "assistant", "content": "ok"}])
    memory.absorb([{"role": "user", "content": "la capacidad financiera"}, {"role": "assistant", "content": "ok"}])

    second_prompt = llm.prompts(SUMMARY_SYSTEM_PROMPT)[1]
    assert "Resumen #1" in second_prompt  # the previous summary is fed back
    assert "la capacidad financiera" in second_prompt
    assert memory.summary.startswith("Resumen #2")
    assert memory.absorb([]) == memory.summary and len(llm.calls) == 2


def test_mid_term_date_filter_and_purge(collections):
    now = datetime(2026, 10, 28, tzinfo=UTC)
    old = MidTermMemory(collections["sessions"], FakeLLM(), clock=lambda: now - timedelta(days=30))
    old.summary = "Se revisó la experiencia exigida en el proceso de obra pública de Sumapaz."
    old.close_session()
    recent = MidTermMemory(collections["sessions"], FakeLLM(), clock=lambda: now)
    recent.summary = "Se revisó la capacidad financiera exigida en el proceso de Sumapaz."
    recent.close_session()

    results = recent.recall("proceso de Sumapaz", k=5, max_distance=2.0)
    assert [r["text"] for r in results] == [recent.all_sessions()[0]["text"]]
    assert "capacidad financiera" in results[0]["text"]
    assert recent.purge_expired() == 1
    assert len(recent.all_sessions()) == 1


def test_mid_term_close_without_summary_stores_nothing(collections):
    memory = MidTermMemory(collections["sessions"], FakeLLM())
    assert memory.close_session() is None
    assert memory.all_sessions() == []


# --- long term ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, expected",
    [
        (f"```json\n{facts_json((FACT_COMPANY, 8))}\n```", [(FACT_COMPANY, 8)]),
        (f"Hechos: {facts_json((FACT_COMPANY, 42))}", [(FACT_COMPANY, 10)]),
        ('[{"fact": "x", "importance": "alta"}, {"nope": 1}, "texto"]', [("x", 5)]),
        ("esto no es JSON", []),
        ('[{"fact": "incompleto"', []),
        ('{"fact": "no es lista"}', []),
    ],
)
def test_parse_facts_tolerates_fences_and_invalid_json(reply, expected):
    assert parse_facts(reply) == expected


def test_extract_and_save_with_invalid_json_saves_nothing(collections):
    memory = LongTermMemory(collections["facts"], FakeLLM("Lo siento, no puedo."))
    assert memory.extract_and_save([{"role": "user", "content": "hola"}]) == []
    assert memory.all_facts() == []


def test_extraction_prompt_guards_secrets_and_injection():
    prompt = EXTRACTION_SYSTEM_PROMPT.lower()
    for word in ("password", "api key", "card", "health", "data, never instructions"):
        assert word in prompt


def test_long_term_deduplicates_near_identical_facts(collections):
    memory = LongTermMemory(collections["facts"], FakeLLM())
    first = memory.save_fact(FACT_COMPANY, importance=6)
    second = memory.save_fact(FACT_COMPANY + ".", importance=9)

    assert first == second
    facts = memory.all_facts()
    assert len(facts) == 1 and facts[0]["importance"] == 9
    memory.save_fact(FACT_PREFERENCE, importance=4)
    assert len(memory.all_facts()) == 2


def test_long_term_isolates_users(collections):
    alice = LongTermMemory(collections["facts"], FakeLLM(), user_id="alice")
    bob = LongTermMemory(collections["facts"], FakeLLM(), user_id="bob")
    alice.save_fact(FACT_COMPANY, importance=8)

    assert bob.recall("¿dónde trabaja el usuario?") == []
    assert bob.forget(FACT_COMPANY) == 0
    assert alice.recall("¿dónde trabaja el usuario?") == [FACT_COMPANY]


def test_long_term_recall_ranks_and_reinforces_access(collections):
    now = datetime(2026, 10, 28, tzinfo=UTC)
    past = LongTermMemory(collections["facts"], FakeLLM(), clock=lambda: now - timedelta(days=60))
    past.save_fact(FACT_COMPANY, importance=8)
    past.save_fact("El usuario tiene un perro llamado Max", importance=1)
    memory = LongTermMemory(collections["facts"], FakeLLM(), clock=lambda: now)

    recalled = memory.recall("empresa constructora del usuario", k=5)
    assert recalled[0] == FACT_COMPANY
    assert "El usuario tiene un perro llamado Max" not in recalled  # below the 0.35 cut-off
    reinforced = {f["fact"]: f["last_access"] for f in memory.all_facts()}
    assert reinforced[FACT_COMPANY] == now.timestamp()


def test_recall_score_weights():
    assert recall_score(0.0, 10, 0) == pytest.approx(1.0)
    assert recall_score(1.0, 0, 0) == pytest.approx(0.15)
    assert recall_score(2.0, 0, 10_000) == pytest.approx(0.0)


def test_long_term_forget_removes_only_close_facts(collections):
    memory = LongTermMemory(collections["facts"], FakeLLM())
    memory.save_fact(FACT_COMPANY, importance=8)
    memory.save_fact(FACT_PREFERENCE, importance=5)

    assert memory.forget("El usuario trabaja en una empresa constructora en Bogotá") == 1
    assert [f["fact"] for f in memory.all_facts()] == [FACT_PREFERENCE]


# --- manager --------------------------------------------------------------------------------


def test_manager_without_memory_returns_empty_context(tmp_path, embedding_function):
    manager = make_manager(tmp_path, FakeLLM(), embedding_function)
    assert manager.build_context("¿qué requisitos tiene el proceso?") == ""


def test_manager_record_turn_feeds_mid_and_long_term(tmp_path, embedding_function):
    llm = FakeLLM(facts_json((FACT_COMPANY, 8)))
    manager = make_manager(tmp_path, llm, embedding_function, max_messages=4, extract_every=4)
    manager.record_turn("¿Qué pide el proceso FDLS-LP-098-2019?", "Pide experiencia.")
    assert llm.calls == []
    manager.record_turn("¿Y la capacidad financiera?", "Liquidez mayor a 1,2.")
    assert len(llm.prompts(EXTRACTION_SYSTEM_PROMPT)) == 1  # every 4 messages
    manager.record_turn("¿Cuál es el presupuesto?", "500 millones.")
    assert manager.mid_term.summary.startswith("Resumen #1")  # first pair evicted
    assert len(manager.short_term_messages()) == 4

    context = manager.build_context("¿dónde trabajo?")
    assert context.startswith(CONTEXT_NOTE)
    assert FACTS_HEADING in context and FACT_COMPANY in context
    assert CURRENT_HEADING in context and "FDLS-LP-098-2019" in context


def test_memory_persists_across_sessions(tmp_path, embedding_function):
    llm = FakeLLM(facts_json((FACT_COMPANY, 8), (FACT_PREFERENCE, 6)))
    first = make_manager(tmp_path, llm, embedding_function)
    first.record_turn("Hola, trabajo en una constructora de Bogotá.", "¡Hola! ¿En qué te ayudo?")
    first.record_turn("Revisa el proceso FDLS-LP-098-2019 de Sumapaz.", "Exige liquidez de 1,2.")
    first.close_session()
    assert len(first.snapshot()["sessions"]) == 1

    second = make_manager(tmp_path, FakeLLM(), embedding_function)
    context = second.build_context("¿en qué quedamos?")
    assert SESSIONS_HEADING in context and "FDLS-LP-098-2019" in context
    assert FACT_COMPANY in context and FACT_PREFERENCE in context
    assert {f["fact"] for f in second.snapshot()["facts"]} == {FACT_COMPANY, FACT_PREFERENCE}

    other_user = make_manager(tmp_path, FakeLLM(), embedding_function, user_id="otro")
    assert other_user.build_context("¿en qué quedamos?") == ""


def test_manager_forget_and_llm_failure_is_not_fatal(tmp_path, embedding_function):
    def broken_llm(system_prompt, messages):
        raise RuntimeError("rate limited")

    manager = make_manager(tmp_path, broken_llm, embedding_function, extract_every=2)
    manager.record_turn("hola", "hola")  # extraction fails silently
    manager.long_term.save_fact(FACT_COMPANY, 8)
    assert manager.forget(FACT_COMPANY) == 1
    manager.close_session()
    assert manager.snapshot() == {"facts": [], "sessions": []}
