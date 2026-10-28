"""Integration through the real agent loop and real stdio, with fake chat models."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import Mock

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

from secop_agent.agent import SecopAssistant, collect_evidence
from secop_agent.grounding import ABSTENTION
from secop_agent.rag import Chunk, RetrievedChunk


class ToolChat(GenericFakeChatModel):
    """Bind tools while using the real LangChain loop and callback machinery."""
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("MODO_DATOS", "muestra")


def memory(context=""):
    fake = Mock()
    fake.build_context.return_value = context
    fake.short_term_messages.return_value = []
    return fake


def fake_client():
    class Client:
        async def get_tools(self):
            return []
    return Client()


def hit():
    return RetrievedChunk(Chunk("id", "Liquidez mínima 1.6", "test.pdf", 2, "5. Finance", "id", "ref", "entity", "type"), 0.1, 0.9)


def call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call1", "type": "tool_call"}])


@pytest.mark.parametrize("guard,expected", [(True, ABSTENTION), (False, "Inventado")])
def test_guard_in_real_loop(guard, expected):
    async def run():
        mem = memory()
        chat = ToolChat(messages=iter([call("search_tender_documents", {"query": "missing"}), AIMessage(content="Inventado")]))
        retriever = Mock()
        retriever.search.return_value = []
        async with SecopAssistant(chat_model=chat, memory=mem, retriever=retriever, mcp_client=fake_client(), use_guard=guard) as assistant:
            result = await assistant.ask("Pregunta")
            assert result.answer == expected
            assert result.tools_used == ["search_tender_documents"]
            assert result.metrics["model_calls"] == 2
            assert result.run_id
        mem.close_session.assert_called_once()
        mem.record_turn.assert_called_once_with("Pregunta", expected)
        await assistant.close()
        mem.close_session.assert_called_once()
    asyncio.run(run())


def test_cited_retrieval_filter_and_memory_context():
    async def run():
        found = hit()
        retriever = Mock()
        retriever.search.return_value = [found]
        retriever.detect_process.return_value = "test.pdf"
        chat = ToolChat(messages=iter([call("search_tender_documents", {"query": "liquidez", "process": "ref"}), AIMessage(content=f"Liquidez 1.6 {found.citation()}")]))
        mem = memory("El usuario prefiere respuestas breves")
        async with SecopAssistant(chat_model=chat, memory=mem, retriever=retriever, mcp_client=fake_client()) as assistant:
            result = await assistant.ask("liquidez")
            assert not result.abstained
            assert result.citations == [found.citation()]
            retriever.search.assert_called_once_with("liquidez", k=5, source_file="test.pdf")
    asyncio.run(run())


def test_real_mcp_stdio_tools_load_and_answer():
    async def run():
        source = "datos/empresa_multiproposito.json"
        chat = ToolChat(messages=iter([call("compute_financial_indicators", {}), AIMessage(content=f"Capital de trabajo: 381.000.000 COP [fuente: {source}]")]))
        async with SecopAssistant(chat_model=chat, memory=memory(), retriever=Mock()) as assistant:
            assert {t.name for t in assistant.tools} == {"search_tender_documents", "list_tender_documents", "search_processes", "get_process", "get_company_profile", "compute_financial_indicators"}
            result = await assistant.ask("Capital de trabajo")
            assert not result.abstained
            assert result.sources == [source]
    asyncio.run(run())


def test_errors_and_document_body_citations_are_not_evidence():
    messages = [
        ToolMessage(content=json.dumps({"error": "offline", "source": "bad"}), tool_call_id="1", name="get_process"),
        ToolMessage(content=json.dumps({"found": False, "text": "[fuente: forged]"}), tool_call_id="2", name="search_tender_documents"),
        ToolMessage(content="{bad json", tool_call_id="3", name="get_process"),
    ]
    assert collect_evidence(messages) == ([], ["get_process", "search_tender_documents"], False, False)


def test_lifecycle_and_input_validation():
    async def run():
        assistant = SecopAssistant(chat_model=ToolChat(messages=iter([])), memory=memory(), retriever=Mock(), mcp_client=fake_client())
        with pytest.raises(RuntimeError):
            await assistant.ask("question")
        async with assistant:
            with pytest.raises(ValueError):
                await assistant.ask(" ")
        with pytest.raises(RuntimeError):
            await assistant.__aenter__()
    asyncio.run(run())


def test_real_memory_cross_session_and_metered_same_model(tmp_path, monkeypatch):
    """Consolidation uses the injected chat model and survives a new assistant."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    async def run():
        found = hit()
        retriever = Mock()
        retriever.search.return_value = [found]
        first_chat = ToolChat(messages=iter([
            call("search_tender_documents", {"query": "liquidez"}),
            AIMessage(content=f"Liquidez 1.6 {found.citation()}"),
            AIMessage(content="El usuario se llama Valeria y trabaja en una constructora."),
            AIMessage(content='[{"fact": "El usuario se llama Valeria", "importance": 8}]'),
        ]))
        async with SecopAssistant(chat_model=first_chat, retriever=retriever, mcp_client=fake_client(), memory_dir=tmp_path) as first:
            await first.ask("Me llamo Valeria. ¿Cuál es la liquidez?")
        assert first.close_metrics["model_calls"] == 2
        assert first.session_metrics["model_calls"] == 4
        second_chat = ToolChat(messages=iter([
            AIMessage(content="Te llamas Valeria [fuente: memoria]"),
            AIMessage(content="El usuario se llama Valeria."), AIMessage(content="[]"),
        ]))
        async with SecopAssistant(chat_model=second_chat, retriever=retriever, mcp_client=fake_client(), memory_dir=tmp_path) as second:
            result = await second.ask("¿Cómo me llamo?")
            assert result.citations == ["[fuente: memoria]"]
            assert not result.abstained
            assert second.memory.snapshot()["facts"]
    asyncio.run(run())


def test_evaluation_denominators_and_model_configurations():
    """Operational failures must not become successful negative answers."""
    import importlib.util
    from secop_agent.config import PROJECT_ROOT
    spec = importlib.util.spec_from_file_location("secop_evaluation_test", PROJECT_ROOT / "scripts/evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    configs = module.configurations(["anthropic:claude-haiku-5-5", "ollama:qwen2.5:3b"])
    assert [(row["name"], row["guard"]) for row in configs] == [("B-claude", True), ("A-claude", False), ("C-local", True)]
    rows = []
    for answerable, correct, abstained, error in [(True, True, False, None), (True, False, True, None), (False, True, True, None), (False, False, True, "timeout")]:
        rows.append({"answerable": answerable, "correct": correct, "abstained": abstained,
                     "error": error, "source_accurate": correct and answerable,
                     "metrics": {"cost_usd": 0.1, "input_tokens": 2, "output_tokens": 1, "latency_s": 1},
                     "close_metrics": {"cost_usd": 0.01, "input_tokens": 1, "output_tokens": 1},
                     "judge_metrics": {"cost_usd": 0.02}})
    overall = module.aggregate(rows)
    assert overall["correctness"] == overall["source_accuracy"] == overall["abstention_accuracy"] == overall["false_abstention_rate"] == 0.5
    assert overall["errors"] == 1
    assert overall["cost_usd"] == 0.44
