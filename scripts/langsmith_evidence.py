"""Export read-only LangSmith measurements and verified trace links as Markdown."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from langsmith import Client

from secop_agent.config import RESULTS_DIR, get_settings

SELECTS = [
    "id", "name", "run_type", "start_time", "end_time", "total_tokens",
    "total_cost", "trace_id", "parent_run_ids", "inputs", "outputs",
]


def number(value: Any, digits: int = 6) -> str:
    """Keep missing provider measurements distinct from zero."""
    return "N/D" if value is None else f"{float(value):.{digits}f}"


def duration(run: Any) -> float | None:
    """Return completed run wall time in seconds."""
    if run.start_time is None or run.end_time is None:
        return None
    return (run.end_time - run.start_time).total_seconds()


async def query_runs(client: Client, project_id: str, **filters: Any) -> list[Any]:
    """Use the current SDK query API, following every cursor page."""
    return [run async for run in client.runs.query(
        project_ids=[project_id], selects=SELECTS, page_size=100,
        include_subtree_usage=True, **filters,
    )]


def final_answer(run: Any) -> str:
    """Read the last assistant text without exporting raw trace payloads."""
    for message in reversed((run.outputs or {}).get("messages", [])):
        if message.get("type") == "ai" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


async def build_report(client: Client | None = None) -> str:
    """Read live server statistics and original runs; make no model calls."""
    client = client or Client()
    report = json.loads((RESULTS_DIR / "evaluacion_rag.json").read_text())
    project = await asyncio.to_thread(
        client.read_project, project_name=get_settings().langsmith_project, include_stats=True,
    )
    project_id = str(project.id)
    base = f"https://smith.langchain.com/o/{project.tenant_id}"
    project_url = f"{base}/projects/p/{project.id}"
    lines = [
        "# Evidencia medida en LangSmith", "",
        f"Consulta de solo lectura: {datetime.now(UTC).isoformat()}. "
        f"Evaluación de referencia: {report['generated_at']}.", "",
        f"[Proyecto {project.name}]({project_url}). Las estadísticas son las que devuelve "
        "LangSmith para todo el proyecto, incluidas ejecuciones anteriores y demostraciones; "
        "no equivalen al coste de esta única evaluación.", "",
        "| Runs (estadística del proyecto) | Tokens | USD | Latencia p50 s | Latencia p99 s |",
        "|---:|---:|---:|---:|---:|",
        f"| {project.run_count} | {project.total_tokens} | {number(project.total_cost)} | "
        f"{number(project.latency_p50.total_seconds() if project.latency_p50 else None)} | "
        f"{number(project.latency_p99.total_seconds() if project.latency_p99 else None)} |", "",
        "## Experimentos y CostCounter", "",
        "Los experimentos publican salidas desde checkpoints: su tiempo es el de publicar la "
        "respuesta, no el de inferencia. Se conserva N/D cuando LangSmith no informa un precio.", "",
        "| Configuración / experimento | n raíces LS | Media LS s | Tokens LS | USD LS | "
        "n CostCounter | Media turno s | Tokens agente + memoria | USD agente + memoria | USD juez |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    experiments = []
    originals: dict[str, list[Any]] = {}
    for experiment in report["langsmith"]["experiments"]:
        session = await asyncio.to_thread(
            client.read_project, project_name=experiment["experiment"], include_stats=True,
        )
        experiments.append(session)
        runs = await query_runs(client, str(session.id), is_root=True)
        result = next(item for item in report["results"]
                      if item["configuration"] == experiment["configuration"])
        score = result["overall"]
        link = f"{base}/datasets/{session.reference_dataset_id}/compare?selectedSessions={session.id}"
        latencies = [value for run in runs if (value := duration(run)) is not None]
        lines.append(
            f"| [{experiment['configuration']}: {session.name}]({link}) | {len(runs)} | "
            f"{number(mean(latencies) if latencies else None)} | {session.total_tokens} | "
            f"{number(session.total_cost)} | {score['questions']} | {number(score['mean_latency_s'])} | "
            f"{score['input_tokens'] + score['output_tokens']} | {number(score['cost_usd'])} | "
            f"{number(score['judge_cost_usd'])} |"
        )
        ids = [row["run_id"] for row in result["questions"] if row.get("run_id")]
        originals[result["configuration"]] = await query_runs(client, project_id, ids=ids)
    compare_url = (f"{base}/datasets/{experiments[0].reference_dataset_id}/compare?selectedSessions="
                   + ",".join(str(session.id) for session in experiments))
    lines += ["", f"[Comparación de los tres experimentos]({compare_url})", "",
              "### Trazas originales de inferencia", "",
              "Se consultan por los run_id del JSON; cada raíz incluye el consumo de su subárbol "
              "una sola vez. No se suman hijos otra vez. Memoria fuera del grafo y jueces tienen "
              "trazas separadas; CostCounter incluye también la consolidación al cierre. "
              "La duración del grafo excluye parte del trabajo exterior medido por el turno.", "",
              "| Configuración | Raíces encontradas / esperadas | Media grafo LS s | Tokens LS | USD LS |",
              "|---|---:|---:|---:|---:|"]
    for result in report["results"]:
        runs = originals[result["configuration"]]
        latencies = [value for run in runs if (value := duration(run)) is not None]
        costs = [run.total_cost for run in runs if run.total_cost is not None]
        lines.append(f"| {result['configuration']} | {len(runs)} / {len(result['questions'])} | "
                     f"{number(mean(latencies) if latencies else None)} | "
                     f"{sum(run.total_tokens or 0 for run in runs)} | "
                     f"{number(sum(costs) if costs else None)} |")
    lines += ["", "A-Claude/q20 no tiene run_id en el JSON tras el límite de pasos; por eso se "
              "encuentran 23 raíces para sus 24 preguntas. LangSmith puede carecer de precio "
              "para Ollama; cero o N/D no valora hardware "
              "ni energía. Sus precios, redondeos y alcance pueden diferir de la tabla local. "
              "El juez se paga incluso cuando evalúa respuestas locales. La precisión de fuente "
              "del informe usa 16 respondibles; el promedio de feedback en LangSmith puede usar 24.",
              "", "## Trazas para inspección y capturas", ""]
    candidates = [
        ("RAG + MCP y respuesta citada (B-Claude/q01)", report["results"][0]["questions"][0]["run_id"]),
        ("«No lo sé» (B-Claude/q17)", report["results"][0]["questions"][16]["run_id"]),
        ("Respuesta contradictoria conservada (B-Claude/q05)", report["results"][0]["questions"][4]["run_id"]),
    ]
    roots = await query_runs(client, project_id, is_root=True, filter='eq(name, "secop-assistant")')
    memory_runs = [run for run in roots
                   if "Me llamo Valeria" in json.dumps(run.inputs, ensure_ascii=False)]
    memory_run = max(memory_runs, key=lambda run: run.start_time) if memory_runs else None
    if memory_run is None:
        raise ValueError("Missing notebook memory demonstration trace")
    if "[fuente:" not in final_answer(memory_run) or final_answer(memory_run).startswith("No lo sé"):
        raise ValueError("Notebook memory demonstration must answer with a citation")
    if memory_run:
        candidates.append(("Notebook: presentación compuesta y liquidez (sesión 1)", memory_run.id))
    by_id = {str(run.id): run for runs in originals.values() for run in runs}
    if memory_run:
        by_id[str(memory_run.id)] = memory_run
    for label, run_id in candidates:
        run = by_id.get(str(run_id))
        if run is None:
            raise ValueError(f"Missing evidence run: {run_id}")
        tree = await query_runs(client, project_id, trace_id=str(run_id))
        tool_names = sorted({node.name for node in tree if node.run_type == "tool"})
        answer = final_answer(run).replace("\n", " ")
        lines += [f"- [{label}]({project_url}/r/{run_id}?traceId={run_id}). "
                  f"Herramientas verificadas en el árbol: {', '.join(tool_names) or 'ninguna'}. "
                  f"Respuesta original del grafo: {answer}"]
    lines += ["", "La respuesta original del grafo precede al guard determinista; la respuesta "
              "entregada y su abstención se verifican en el JSON y el notebook. B-Claude falla "
              "q05 por «Sí, … no se exige»; A-Claude falla q10 por falsa abstención y q20 por "
              "límite de pasos con respuesta vacía. No se corrigen esos fallos al publicar evidencia.", ""]
    return "\n".join(lines)


async def main() -> None:
    """Write the requested evidence artifact without logging credentials."""
    markdown = await build_report()
    output = RESULTS_DIR / "evidencia_langsmith.md"
    output.write_text(markdown, encoding="utf-8")
    print(f"Evidence written to {output.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    asyncio.run(main())
