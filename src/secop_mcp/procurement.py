"""Stateless procurement tools with independently testable filtering and calculations.

Only the data access helpers read files or contact SECOP; importing this module
does neither. Course data retains its original Spanish field names.
"""

from __future__ import annotations

import json
import math
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import requests

from secop_agent.config import DATA_DIR, get_settings

API_URL = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
API_TIMEOUT_SECONDS = 30
SAMPLE_SOURCE = "datos/secop_muestra.json"
COMPANY_SOURCE = "datos/empresa_multiproposito.json"


def _normalize(value: str) -> str:
    """Return case-folded text without accents for local substring matching."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def _validate_date(value: str | None, name: str) -> None:
    """Reject dates that are not real calendar dates in YYYY-MM-DD format."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a date in YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a date in YYYY-MM-DD format") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{name} must be a date in YYYY-MM-DD format")


def _validate_amount(value: float | None, name: str, *, positive: bool = False) -> None:
    """Require finite numeric amounts, rejecting booleans and numeric strings."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be a finite {qualifier} number")


def _data_mode() -> str:
    """Resolve the shared runtime setting without caching environment state."""
    mode = get_settings().data_mode.strip().lower()
    if mode not in {"muestra", "api"}:
        raise ValueError("MODO_DATOS must be 'muestra' or 'api'")
    return mode


def _read_json(path: Path) -> Any:
    """Read UTF-8 course data only when a tool is invoked."""
    return json.loads(path.read_text(encoding="utf-8"))


def _records(value: Any) -> list[dict[str, Any]]:
    """Validate the row container returned by either data source."""
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Expected a list of process objects")
    return value


def _budget(process: dict[str, Any]) -> float:
    """Treat unavailable or malformed published budgets as zero in summaries."""
    try:
        amount = float(process.get("precio_base") or 0)
    except (TypeError, ValueError):
        return 0.0
    return amount if math.isfinite(amount) and amount >= 0 else 0.0


def _matches(
    process: dict[str, Any],
    filters: dict[str, str],
    min_budget: float | None,
    max_budget: float | None,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    """Apply all local filters, including both the entity and unit cities."""
    for field, term in filters.items():
        value = str(process.get(field) or "")
        if field == "ciudad_entidad":
            value += " " + str(process.get("ciudad_de_la_unidad_de") or "")
        if _normalize(term) not in _normalize(value):
            return False
    amount = _budget(process)
    if min_budget is not None and amount < min_budget:
        return False
    if max_budget is not None and amount > max_budget:
        return False
    published = str(process.get("fecha_de_publicacion_del") or "")[:10]
    if (date_from or date_to) and not published:
        return False
    return not ((date_from and published < date_from) or (date_to and published > date_to))


def _soql_literal(value: str) -> str:
    """Quote a SoQL string literal, escaping embedded single quotes."""
    return "'" + value.replace("'", "''") + "'"


def _contains_clause(field: str, term: str) -> str:
    """Use literal substring matching without exposing LIKE wildcards."""
    return f"contains(upper({field}), {_soql_literal(term.upper())})"


def _query_api(conditions: list[str], limit: int) -> dict[str, Any]:
    """Fetch bounded live rows; report failures without falling back to sample data."""
    params: dict[str, str | int] = {
        "$limit": limit,
        "$order": "fecha_de_publicacion_del DESC, id_del_proceso ASC",
    }
    if conditions:
        params["$where"] = " AND ".join(conditions)
    source = requests.Request("GET", API_URL, params=params).prepare().url or API_URL
    try:
        response = requests.get(API_URL, params=params, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        processes = _records(response.json())
    except (requests.RequestException, ValueError) as error:
        return {"error": f"SECOP API request failed ({type(error).__name__})", "source": source}
    return _search_result(processes[:limit], source)


def _search_result(processes: list[dict[str, Any]], source: str) -> dict[str, Any]:
    """Summarize exactly the returned rows, attaching provenance to every row."""
    budgets = [_budget(process) for process in processes]
    total = sum(budgets)
    return {
        "source": source,
        "summary": {
            "count": len(processes),
            "total_budget": total,
            "average_budget": round(total / len(processes), 2) if processes else 0.0,
            "zero_budget_count": sum(amount == 0 for amount in budgets),
            "scope": "returned_processes",
        },
        "processes": [{**process, "source": source} for process in processes],
    }


def search_processes(
    entity: str | None = None,
    department: str | None = None,
    city: str | None = None,
    modality: str | None = None,
    text: str | None = None,
    min_budget: float | None = None,
    max_budget: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Find SECOP II opportunities by entity, location, modality or description.

    Use before inspecting a specific process. Filters combine with AND; city
    matches the entity or purchasing unit. Local matching ignores case and accents;
    live matching ignores case. Dates must be YYYY-MM-DD, inclusive; budgets are
    non-negative COP and limit is 1..50. MODO_DATOS selects muestra (default) or api.
    Summary statistics cover only returned rows, not the whole SECOP dataset.
    Cite source and preserve the distinction between sample and live data.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50")
    _validate_amount(min_budget, "min_budget")
    _validate_amount(max_budget, "max_budget")
    if min_budget is not None and max_budget is not None and min_budget > max_budget:
        raise ValueError("min_budget must not exceed max_budget")
    _validate_date(date_from, "date_from")
    _validate_date(date_to, "date_to")
    if date_from and date_to and date_from > date_to:
        raise ValueError("date_from must not exceed date_to")
    values = {
        "entidad": entity,
        "departamento_entidad": department,
        "ciudad_entidad": city,
        "modalidad_de_contratacion": modality,
        "descripci_n_del_procedimiento": text,
    }
    if any(value is not None and not isinstance(value, str) for value in values.values()):
        raise ValueError("Text filters must be strings")
    filters = {field: value.strip() for field, value in values.items() if value and value.strip()}
    if _data_mode() == "api":
        conditions = []
        for field, term in filters.items():
            clause = _contains_clause(field, term)
            if field == "ciudad_entidad":
                clause = f"({clause} OR {_contains_clause('ciudad_de_la_unidad_de', term)})"
            conditions.append(clause)
        if min_budget is not None:
            conditions.append(f"precio_base >= {float(min_budget)}")
        if max_budget is not None:
            conditions.append(f"precio_base <= {float(max_budget)}")
        if date_from:
            conditions.append(f"fecha_de_publicacion_del >= '{date_from}T00:00:00.000'")
        if date_to:
            conditions.append(f"fecha_de_publicacion_del <= '{date_to}T23:59:59.999'")
        return _query_api(conditions, limit)
    try:
        processes = _records(_read_json(DATA_DIR / "secop_muestra.json"))
    except (OSError, ValueError) as error:
        return {"error": f"Sample data could not be read ({type(error).__name__})", "source": SAMPLE_SOURCE}
    matches = [row for row in processes if _matches(row, filters, min_budget, max_budget, date_from, date_to)]
    return _search_result(matches[:limit], SAMPLE_SOURCE)


def get_process(identifier: str) -> dict[str, Any]:
    """Retrieve one process by its exact reference or SECOP process ID.

    Use after search_processes or when a reference such as FDLS-LP-098-2019 or
    ID such as CO1.REQ.848621 is known. Matching ignores case. Uses MODO_DATOS;
    returns an error with source when absent, never an invented process.
    """
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("identifier must be a non-empty string")
    identifier = identifier.strip()
    if _data_mode() == "api":
        literal = _soql_literal(identifier.upper())
        result = _query_api([
            f"(upper(referencia_del_proceso) = {literal} OR upper(id_del_proceso) = {literal})"
        ], 1)
        if "error" in result:
            return result
        processes, source = result["processes"], result["source"]
    else:
        source = SAMPLE_SOURCE
        try:
            rows = _records(_read_json(DATA_DIR / "secop_muestra.json"))
        except (OSError, ValueError) as error:
            return {"error": f"Sample data could not be read ({type(error).__name__})", "source": source}
        processes = [row for row in rows if any(
            identifier.casefold() == str(row.get(field) or "").casefold()
            for field in ("referencia_del_proceso", "id_del_proceso")
        )]
    if not processes:
        return {"error": "Process not found", "identifier": identifier, "source": source}
    return {**processes[0], "source": source}


def get_company_profile() -> dict[str, Any]:
    """Read the fictional course company's RUP, UNSPSC, finances and experience.

    Use to assess company capabilities before comparing with tender requirements.
    This local academic profile is used in both data modes; it is not a live
    registry lookup. Cite source, and do not infer facts missing from the profile.
    """
    try:
        profile = _read_json(DATA_DIR / "empresa_multiproposito.json")
        if not isinstance(profile, dict):
            raise ValueError("Expected a company object")
    except (OSError, ValueError) as error:
        return {"error": f"Company data could not be read ({type(error).__name__})", "source": COMPANY_SOURCE}
    return {**profile, "source": COMPANY_SOURCE}


def _ratio(numerator: float, denominator: float) -> float | None:
    """Return an unrounded ratio, or null when its denominator is zero."""
    return numerator / denominator if denominator else None


def compute_financial_indicators(process_budget: float | None = None) -> dict[str, Any]:
    """Compute the fictional company's RUP financial and organizational indicators.

    Use when comparing company finances against documented tender thresholds.
    Liquidity = current assets/current liabilities; debt_ratio = liabilities/assets
    (a fraction, not a percentage); interest_coverage = operating profit/interest.
    ROE and ROA use operating profit, following the course RUP formulas, rather
    than net profit. Zero denominators produce null, not an eligibility conclusion.
    Optional process_budget must be positive finite COP; working_capital_pct_of_budget
    is a percentage (0..100 or higher). Cite the company source for every indicator.
    """
    _validate_amount(process_budget, "process_budget", positive=True)
    profile = get_company_profile()
    if "error" in profile:
        return profile
    try:
        statements = profile["estados_financieros"]
        fields = (
            "activo_corriente", "pasivo_corriente", "activo_total", "pasivo_total",
            "patrimonio", "utilidad_operacional", "gastos_de_intereses",
        )
        amounts = {field: float(statements[field]) for field in fields}
        if not all(math.isfinite(value) for value in amounts.values()):
            raise ValueError("Non-finite financial data")
        working_capital = amounts["activo_corriente"] - amounts["pasivo_corriente"]
        indicators = {
            "liquidity": _ratio(amounts["activo_corriente"], amounts["pasivo_corriente"]),
            "debt_ratio": _ratio(amounts["pasivo_total"], amounts["activo_total"]),
            "interest_coverage": _ratio(amounts["utilidad_operacional"], amounts["gastos_de_intereses"]),
            "working_capital": working_capital,
            "roe": _ratio(amounts["utilidad_operacional"], amounts["patrimonio"]),
            "roa": _ratio(amounts["utilidad_operacional"], amounts["activo_total"]),
            "financial_statement_date": statements["corte"],
            "currency": statements["moneda"],
            "source": COMPANY_SOURCE,
        }
    except (KeyError, TypeError, ValueError) as error:
        return {"error": f"Invalid company financial data ({type(error).__name__})", "source": COMPANY_SOURCE}
    if process_budget is not None:
        indicators["working_capital_pct_of_budget"] = 100 * working_capital / process_budget
    return indicators
