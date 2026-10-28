"""Extract all twenty tender requirements and score fourteen fields against the key."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from secop_agent.config import RESULTS_DIR, get_settings
from secop_agent.costs import CostCounter
from secop_agent.extraction import ANSWER_KEY_FIELDS, extract_requirements, score_against_key
from secop_agent.llm import get_chat_model
from secop_agent.rag import TenderRetriever


class MeteredModel:
    """Attach callbacks to structured calls through the extraction injection seam."""
    def __init__(self, model: str, counter: CostCounter) -> None:
        self.chat = get_chat_model(model, max_tokens=2048)
        self.counter = counter

    def with_structured_output(self, schema):
        return self.chat.with_structured_output(schema).with_config(callbacks=[self.counter], run_name="secop-extraction")


def evaluate(models: list[str], *, force: bool = False) -> dict[str, Any]:
    """Checkpoint per PDF; the answer key is read only by the scoring function."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "extraccion_requisitos.json"
    old = json.loads(path.read_text()) if path.exists() and not force else {}
    retriever = TenderRetriever()
    documents = retriever.list_documents()
    report: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), "results": [],
        "local_evaluation": "Executed" if any(m.startswith("ollama:") for m in models) else "Skipped: optional local extraction deferred to keep runtime bounded"}
    for model in models:
        previous = next((r for r in old.get("results", []) if r["model"] == model), {})
        rows = list(previous.get("documents", []))
        result = {"model": model, "documents": rows}
        report["results"].append(result)
        for document in documents:
            source = document["file"]
            if any(row["source"] == source for row in rows):
                continue
            print(f"Extraction · {model} · {source}", flush=True)
            counter, start = CostCounter(model), perf_counter()
            prediction, error = {}, None
            try:
                prediction = extract_requirements(source, retriever=retriever, model=MeteredModel(model, counter))
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            rows.append({"source": source, "prediction": prediction, "error": error,
                         "metrics": {**counter.summary(), "latency_s": perf_counter() - start}})
            result["score"] = score_against_key({row["source"]: row["prediction"] for row in rows})
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        result["score"] = score_against_key({row["source"]: row["prediction"] for row in rows})
        processes = result["score"]["per_process"]
        result["per_field"] = {field: {"correct": sum(p["fields"][field] for p in processes.values()), "total": len(processes),
                                        "accuracy": sum(p["fields"][field] for p in processes.values()) / len(processes)} for field in ANSWER_KEY_FIELDS}
        result["metrics"] = {key: sum(row["metrics"][key] for row in rows) for key in ("model_calls", "input_tokens", "output_tokens", "cost_usd", "latency_s")}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Extracción de requisitos", "", "20 PDF simulados × 14 campos = 280 comparaciones. Tolerancia numérica absoluta: 1e-6; listas sin orden; ausentes cuentan como error.", "",
             "| Modelo | Aciertos | Total | Exactitud | USD | Tokens entrada | Tokens salida | Tiempo s |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for result in report["results"]:
        s, m = result["score"]["overall"], result["metrics"]
        lines.append(f"| {result['model']} | {s['correct']} | {s['total']} | {s['accuracy']:.1%} | {m['cost_usd']:.6f} | {m['input_tokens']} | {m['output_tokens']} | {m['latency_s']:.2f} |")
        lines.extend(["", f"## {result['model']}", "", "| Campo | Aciertos / 20 | Exactitud |", "|---|---:|---:|"])
        lines.extend(f"| {field} | {value['correct']} / {value['total']} | {value['accuracy']:.1%} |" for field, value in result["per_field"].items())
        lines.extend(["", "| PDF | Aciertos / 14 |", "|---|---:|"])
        lines.extend(f"| {source} | {value['correct']} / {value['total']} |" for source, value in result["score"]["per_process"].items())
        for row in result["documents"]:
            if row["error"]:
                lines.append(f"\nError {row['source']}: {row['error']}")
    lines.extend(["", f"Extracción local: {report['local_evaluation']}.", "", "Coste según la tabla del proyecto. No se consulta la clave durante la extracción."])
    (RESULTS_DIR / "extraccion_requisitos.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=[get_settings().chat_model])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    evaluate(args.models, force=args.force)


if __name__ == "__main__":
    main()
