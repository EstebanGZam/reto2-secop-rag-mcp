"""Offline unit tests and real stdio interoperability checks, without LLM keys."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import anyio
import pytest
import requests
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from secop_agent.config import PROJECT_ROOT
from secop_mcp import procurement

TOOL_NAMES = {
    "search_processes", "get_process", "get_company_profile", "compute_financial_indicators",
}
PROCESS_REFERENCE = "FDLS-LP-098-2019"
PROCESS_ID = "CO1.REQ.848621"


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make local data the deterministic default and explicitly disable credentials."""
    monkeypatch.setenv("MODO_DATOS", "muestra")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


def test_sample_search_and_summary() -> None:
    result = procurement.search_processes()
    assert result["summary"]["count"] == 20
    assert result["summary"]["zero_budget_count"] == 1
    assert result["summary"]["scope"] == "returned_processes"
    assert result["summary"]["total_budget"] == sum(float(row["precio_base"]) for row in result["processes"])
    assert all(row["source"] == procurement.SAMPLE_SOURCE for row in result["processes"])
    assert result["source"] == procurement.SAMPLE_SOURCE


def test_combined_filters_ignore_accents_and_case() -> None:
    result = procurement.search_processes(
        entity="alcaldía", department="BOGOTA", city="bogota", modality="licitaci",
        text="CONSERVACION", min_budget=600000000, max_budget=600000000,
        date_from="2019-04-29", date_to="2019-04-29",
    )
    assert [row["referencia_del_proceso"] for row in result["processes"]] == [PROCESS_REFERENCE]
    assert result["summary"]["total_budget"] == 600000000


def test_city_also_matches_purchasing_unit() -> None:
    result = procurement.search_processes(city="pasto")
    assert [row["referencia_del_proceso"] for row in result["processes"]] == ["135116"]


def test_limit_and_empty_search_summary() -> None:
    limited = procurement.search_processes(limit=1)
    assert limited["summary"]["count"] == 1
    assert limited["summary"]["total_budget"] == float(limited["processes"][0]["precio_base"])
    empty = procurement.search_processes(text="no matching description exists")
    assert empty["processes"] == []
    assert empty["summary"] == {
        "count": 0, "total_budget": 0, "average_budget": 0.0,
        "zero_budget_count": 0, "scope": "returned_processes",
    }
    assert empty["source"]


@pytest.mark.parametrize("arguments", [
    {"limit": 0}, {"limit": 51}, {"limit": True}, {"limit": 2.5}, {"limit": "2"},
    {"date_from": "2026-02-30"}, {"date_to": "20261001"},
    {"date_from": "2026-1-01"}, {"date_to": "2026-01-01T00:00:00"},
    {"date_from": "2026-02-01", "date_to": "2026-01-01"},
    {"min_budget": -1}, {"max_budget": float("inf")}, {"min_budget": float("nan")},
    {"min_budget": 2, "max_budget": 1}, {"min_budget": "2"}, {"entity": 1},
])
def test_search_rejects_invalid_inputs(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        procurement.search_processes(**arguments)


def test_invalid_mode_is_not_silently_treated_as_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODO_DATOS", "typo")
    with pytest.raises(ValueError, match="MODO_DATOS"):
        procurement.search_processes()


@pytest.mark.parametrize("identifier", [PROCESS_REFERENCE, PROCESS_ID, " fdls-lp-098-2019 "])
def test_get_process_by_reference_or_id(identifier: str) -> None:
    result = procurement.get_process(identifier)
    assert result["id_del_proceso"] == PROCESS_ID
    assert result["referencia_del_proceso"] == PROCESS_REFERENCE
    assert float(result["precio_base"]) == 600000000
    assert result["source"] == procurement.SAMPLE_SOURCE


def test_get_process_requires_exact_identifier() -> None:
    result = procurement.get_process("FDLS")
    assert result["error"] == "Process not found"
    assert result["source"] == procurement.SAMPLE_SOURCE
    with pytest.raises(ValueError, match="non-empty"):
        procurement.get_process(" ")


def test_company_profile_and_indicators() -> None:
    profile = procurement.get_company_profile()
    assert profile["source"] == procurement.COMPANY_SOURCE
    assert profile["rup"]["vigente"] is True
    assert len(profile["experiencia"]) == 9
    indicators = procurement.compute_financial_indicators(600000000)
    assert indicators["liquidity"] == pytest.approx(727 / 346)
    assert indicators["debt_ratio"] == pytest.approx(0.55)
    assert indicators["interest_coverage"] == pytest.approx(3.2)
    assert indicators["working_capital"] == 381000000
    assert indicators["working_capital_pct_of_budget"] == pytest.approx(63.5)
    assert indicators["roe"] == pytest.approx(126 / 810)
    assert indicators["roa"] == pytest.approx(126 / 1800)
    assert indicators["financial_statement_date"] == "2025-12-31"
    assert indicators["source"] == procurement.COMPANY_SOURCE
    assert "working_capital_pct_of_budget" not in procurement.compute_financial_indicators()


@pytest.mark.parametrize("budget", [0, -1, float("inf"), float("nan"), True, "600000000"])
def test_financial_budget_requires_positive_finite_number(budget: Any) -> None:
    with pytest.raises(ValueError, match="process_budget"):
        procurement.compute_financial_indicators(budget)


def test_zero_denominators_are_json_null(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = procurement.get_company_profile()
    statements = profile["estados_financieros"]
    for field in ("pasivo_corriente", "activo_total", "patrimonio", "gastos_de_intereses"):
        statements[field] = 0
    monkeypatch.setattr(procurement, "get_company_profile", lambda: profile)
    result = procurement.compute_financial_indicators()
    assert all(result[key] is None for key in ("liquidity", "debt_ratio", "interest_coverage", "roe", "roa"))
    json.dumps(result, allow_nan=False)


@pytest.fixture
def api_response(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Serve known sample rows as a fake HTTP response without external requests."""
    process = procurement.get_process(PROCESS_REFERENCE)
    process.pop("source")
    response = Mock()
    response.json.return_value = [process]
    getter = Mock(return_value=response)
    monkeypatch.setattr(procurement.requests, "get", getter)
    monkeypatch.setenv("MODO_DATOS", "api")
    return getter


def test_api_query_escapes_literals_and_uses_timeout(api_response: Mock) -> None:
    result = procurement.search_processes(
        entity="O'Brien' OR 1=1 --", department="Bogotá", city="Cali", modality="licitaci",
        text="100%_bridge", min_budget=0, max_budget=600000000,
        date_from="2019-04-29", date_to="2019-04-29", limit=3,
    )
    args, kwargs = api_response.call_args
    assert args == (procurement.API_URL,)
    assert kwargs["timeout"] == 30
    params = kwargs["params"]
    assert params["$limit"] == 3
    where = params["$where"]
    assert "'O''BRIEN'' OR 1=1 --'" in where
    assert "contains(upper(descripci_n_del_procedimiento), '100%_BRIDGE')" in where
    assert "upper(ciudad_entidad)" in where and "upper(ciudad_de_la_unidad_de)" in where
    assert "precio_base >= 0.0" in where
    assert "precio_base <= 600000000.0" in where
    assert "2019-04-29T00:00:00.000" in where and "2019-04-29T23:59:59.999" in where
    assert result["source"].startswith(procurement.API_URL)
    assert parse_qs(urlparse(result["source"]).query)["$where"] == [where]
    assert result["processes"][0]["source"] == result["source"]


def test_api_get_process_queries_exact_identifiers(api_response: Mock) -> None:
    result = procurement.get_process("o'brien")
    where = api_response.call_args.kwargs["params"]["$where"]
    assert where == "(upper(referencia_del_proceso) = 'O''BRIEN' OR upper(id_del_proceso) = 'O''BRIEN')"
    assert api_response.call_args.kwargs["params"]["$limit"] == 1
    assert result["id_del_proceso"] == PROCESS_ID
    assert result["source"].startswith(procurement.API_URL)
    api_response.return_value.json.return_value = []
    assert procurement.get_process("missing")["error"] == "Process not found"


@pytest.mark.parametrize("failure", [requests.Timeout("offline"), requests.HTTPError("503")])
def test_api_network_errors_preserve_source_without_sample_fallback(api_response: Mock, failure: Exception) -> None:
    api_response.side_effect = failure
    for result in (procurement.search_processes(), procurement.get_process(PROCESS_ID)):
        assert "error" in result and "processes" not in result
        assert result["source"].startswith(procurement.API_URL)


@pytest.mark.parametrize("payload", [{"error": "invalid query"}, ["invalid row"], None])
def test_api_rejects_malformed_responses(api_response: Mock, payload: Any) -> None:
    api_response.return_value.json.return_value = payload
    result = procurement.search_processes()
    assert "error" in result and result["source"].startswith(procurement.API_URL)


def test_api_invalid_json_is_graceful(api_response: Mock) -> None:
    api_response.return_value.json.side_effect = ValueError("invalid JSON")
    assert "error" in procurement.search_processes()


def test_missing_local_files_return_citable_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(procurement, "DATA_DIR", tmp_path)
    for result in (
        procurement.search_processes(), procurement.get_process(PROCESS_ID),
        procurement.get_company_profile(), procurement.compute_financial_indicators(),
    ):
        assert "error" in result and result["source"].startswith("datos/")


def test_invalid_financial_data_is_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(procurement, "get_company_profile", lambda: {"estados_financieros": {}})
    result = procurement.compute_financial_indicators()
    assert "error" in result and result["source"] == procurement.COMPANY_SOURCE


@pytest.mark.parametrize("launch", ["module", "console"])
def test_official_client_over_real_stdio(launch: str, tmp_path: Path) -> None:
    """Exercise discovery and calls through a real subprocess from another cwd."""
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable if launch == "module" else str(Path(sys.executable).with_name("secop-mcp")),
            args=["-m", "secop_mcp.server"] if launch == "module" else [],
            cwd=str(tmp_path),
            env={"MODO_DATOS": "muestra", "ANTHROPIC_API_KEY": "", "LANGSMITH_TRACING": "false"},
        )
        with anyio.fail_after(30):
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "secop"
                    listed = await session.list_tools()
                    assert {tool.name for tool in listed.tools} == TOOL_NAMES
                    assert all(tool.description for tool in listed.tools)
                    for name, arguments in (
                        ("search_processes", {"modality": "licitaci"}),
                        ("get_process", {"identifier": PROCESS_REFERENCE}),
                        ("get_company_profile", {}),
                        ("compute_financial_indicators", {"process_budget": 600000000}),
                    ):
                        result = await session.call_tool(name, arguments)
                        assert not result.isError
                        payload = json.loads(result.content[0].text)
                        assert payload["source"]
                        if name == "search_processes":
                            assert payload["summary"]["count"] == 2
                            assert PROCESS_REFERENCE in {row["referencia_del_proceso"] for row in payload["processes"]}
                        elif name == "get_process":
                            assert payload["id_del_proceso"] == PROCESS_ID
                            assert float(payload["precio_base"]) == 600000000
                        elif name == "get_company_profile":
                            assert payload["estados_financieros"]["activo_corriente"] == 727000000
                        else:
                            assert payload["liquidity"] == pytest.approx(727 / 346)
                            assert payload["working_capital_pct_of_budget"] == 63.5
                    invalid = await session.call_tool("search_processes", {"limit": 0})
                    assert invalid.isError
                    # A bad call must not kill the server or corrupt its stdout protocol.
                    assert not (await session.call_tool("get_company_profile", {})).isError
    asyncio.run(exercise())


def test_langchain_adapter_get_tools_and_invoke(tmp_path: Path) -> None:
    """Verify the exact client path used by SecopAssistant, without a model."""
    async def exercise() -> None:
        client = MultiServerMCPClient({
            "secop": {
                "transport": "stdio", "command": sys.executable,
                "args": ["-m", "secop_mcp.server"], "cwd": str(tmp_path),
                "env": {"MODO_DATOS": "muestra", "ANTHROPIC_API_KEY": "", "LANGSMITH_TRACING": "false"},
            },
        })
        with anyio.fail_after(30):
            tools = {tool.name: tool for tool in await client.get_tools()}
            assert set(tools) == TOOL_NAMES
            for name, arguments in (
                ("search_processes", {"modality": "licitaci"}),
                ("get_process", {"identifier": PROCESS_REFERENCE}),
                ("compute_financial_indicators", {"process_budget": 600000000}),
            ):
                output = await tools[name].ainvoke(arguments)
                payload = json.loads(output if isinstance(output, str) else output[0]["text"])
                assert payload["source"]
                if name == "search_processes":
                    assert payload["summary"]["count"] == 2
                elif name == "get_process":
                    assert payload["id_del_proceso"] == PROCESS_ID
                else:
                    assert payload["liquidity"] == pytest.approx(727 / 346)
    asyncio.run(exercise())


def test_vscode_mcp_configuration() -> None:
    config = json.loads((PROJECT_ROOT / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    assert config["servers"]["secop"] == {
        "type": "stdio", "command": "uv",
        "args": ["--directory", "${workspaceFolder}", "run", "secop-mcp"],
    }
    assert config["servers"]["memory"] == {
        "type": "stdio", "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env": {"MEMORY_FILE_PATH": "${workspaceFolder}/memoria/memory.jsonl"},
    }
