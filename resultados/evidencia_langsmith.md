# Evidencia medida en LangSmith

Consulta de solo lectura: 2026-10-28T21:09:58.901621+00:00. Evaluación de referencia: 2026-10-28T21:09:54.852612+00:00.

[Proyecto secop-reto2-rag-mcp](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/projects/p/6f480c7b-d861-4a8b-af41-8211bf4a1efc). Las estadísticas son las que devuelve LangSmith para todo el proyecto, incluidas ejecuciones anteriores y demostraciones; no equivalen al coste de esta única evaluación.

| Runs (estadística del proyecto) | Tokens | USD | Latencia p50 s | Latencia p99 s |
|---:|---:|---:|---:|---:|
| 661 | 1818261 | 0.223304 | 1.576040 | 11.189552 |

## Experimentos y CostCounter

Los experimentos publican salidas desde checkpoints: su tiempo es el de publicar la respuesta, no el de inferencia. Se conserva N/D cuando LangSmith no informa un precio.

| Configuración / experimento | n raíces LS | Media LS s | Tokens LS | USD LS | n CostCounter | Media turno s | Tokens agente + memoria | USD agente + memoria | USD juez |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [B-claude: B-claude-2965150d](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/datasets/acf6ac2c-1ee2-42dd-8b9a-f39e61411058/compare?selectedSessions=bfd8c469-4578-4a4f-bdb3-4d8f698a2c41) | 24 | 0.000436 | 0 | 0.000000 | 24 | 5.037036 | 270187 | 0.035452 | 0.003996 |
| [A-claude: A-claude-ca03fc28](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/datasets/acf6ac2c-1ee2-42dd-8b9a-f39e61411058/compare?selectedSessions=42f1f936-2520-4ad3-9da2-d1fbedb1f44b) | 24 | 0.000506 | 0 | 0.000000 | 24 | 5.155862 | 291924 | 0.036906 | 0.003826 |
| [C-local: C-local-7aba5c18](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/datasets/acf6ac2c-1ee2-42dd-8b9a-f39e61411058/compare?selectedSessions=70effc14-7239-45be-bbfb-0e488b02a527) | 24 | 0.000504 | 0 | 0.000000 | 24 | 2.229281 | 64339 | 0.000000 | 0.003683 |

[Comparación de los tres experimentos](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/datasets/acf6ac2c-1ee2-42dd-8b9a-f39e61411058/compare?selectedSessions=bfd8c469-4578-4a4f-bdb3-4d8f698a2c41,42f1f936-2520-4ad3-9da2-d1fbedb1f44b,70effc14-7239-45be-bbfb-0e488b02a527)

### Trazas originales de inferencia

Se consultan por los run_id del JSON; cada raíz incluye el consumo de su subárbol una sola vez. No se suman hijos otra vez. Memoria fuera del grafo y jueces tienen trazas separadas; CostCounter incluye también la consolidación al cierre. La duración del grafo excluye parte del trabajo exterior medido por el turno.

| Configuración | Raíces encontradas / esperadas | Media grafo LS s | Tokens LS | USD LS |
|---|---:|---:|---:|---:|
| B-claude | 24 / 24 | 5.005930 | 238549 | 0.028700 |
| A-claude | 23 / 24 | 4.760164 | 217273 | 0.026099 |
| C-local | 24 / 24 | 2.203452 | 50812 | N/D |

A-Claude/q20 no tiene run_id en el JSON tras el límite de pasos; por eso se encuentran 23 raíces para sus 24 preguntas. LangSmith puede carecer de precio para Ollama; cero o N/D no valora hardware ni energía. Sus precios, redondeos y alcance pueden diferir de la tabla local. El juez se paga incluso cuando evalúa respuestas locales. La precisión de fuente del informe usa 16 respondibles; el promedio de feedback en LangSmith puede usar 24.

## Trazas para inspección y capturas

- [RAG + MCP y respuesta citada (B-Claude/q01)](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/projects/p/6f480c7b-d861-4a8b-af41-8211bf4a1efc/r/4547531b-8e2a-48b0-99e2-4d632e08b79e?traceId=4547531b-8e2a-48b0-99e2-4d632e08b79e). Herramientas verificadas en el árbol: get_process, search_tender_documents. Respuesta original del grafo: El presupuesto oficial de EDP-545-2022 es de **$57.333.333 COP**. [fuente: 01_EDP_545_2022.pdf, p. 1, §1 Información general del proceso]
- [«No lo sé» (B-Claude/q17)](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/projects/p/6f480c7b-d861-4a8b-af41-8211bf4a1efc/r/6f7c4b90-79ff-4880-94de-ac238d6114bf?traceId=6f7c4b90-79ff-4880-94de-ac238d6114bf). Herramientas verificadas en el árbol: search_tender_documents. Respuesta original del grafo: No lo sé. Busqué en los documentos del pliego los términos "seguro de vida del gerente", "seguro de vida" y "gerente", y ninguno devolvió resultados, así que no encuentro en las fuentes disponibles ninguna disposición sobre un seguro de vida para el gerente.  Si me indica el identificador del proceso (por ejemplo, una referencia como "FDLS-LP-098-2019" o un ID "CO1.REQ.…"), puedo volver a buscar dentro de ese proceso específico.
- [Respuesta contradictoria conservada (B-Claude/q05)](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/projects/p/6f480c7b-d861-4a8b-af41-8211bf4a1efc/r/c24c521b-d320-4b00-acb8-1e654c07e4fb?traceId=c24c521b-d320-4b00-acb8-1e654c07e4fb). Herramientas verificadas en el árbol: list_tender_documents, search_tender_documents. Respuesta original del grafo: Sí, en el proceso 5 (PS-147-2025, Municipio de San Miguel Putumayo) no se exige la constitución de garantías. El estudio previo indica que, de conformidad con el análisis de riesgos, no se exige la constitución de garantías para este contrato [fuente: 05_PS_147_2025.pdf, p. 2, §7 Garantías].  Nota: asumí que "proceso 5" se refiere al quinto documento indexado (PS-147-2025).
- [Notebook: presentación compuesta y liquidez (sesión 1)](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/projects/p/6f480c7b-d861-4a8b-af41-8211bf4a1efc/r/6c8585cb-8aad-454a-9447-df5a2282e40b?traceId=6c8585cb-8aad-454a-9447-df5a2282e40b). Herramientas verificadas en el árbol: search_tender_documents. Respuesta original del grafo: El índice de liquidez mínimo exigido en el proceso FDLS-LP-098-2019 es de **1.6** (mayor o igual a 1.6). [fuente: 11_FDLS_LP_098_2019.pdf, p. 2, §5 Capacidad financiera y organizacional (según RUP)]

La respuesta original del grafo precede al guard determinista; la respuesta entregada y su abstención se verifican en el JSON y el notebook. B-Claude falla q05 por «Sí, … no se exige»; A-Claude falla q10 por falsa abstención y q20 por límite de pasos con respuesta vacía. No se corrigen esos fallos al publicar evidencia.
