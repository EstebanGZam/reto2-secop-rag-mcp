# Capturas de LangSmith

Tomadas de la interfaz web de LangSmith el 28/10/2026, sobre el proyecto `secop-reto2-rag-mcp` y el dataset `secop-reto2-pliegos`. Las mediciones consultadas por API y los enlaces exactos están en [evidencia_langsmith.md](../../resultados/evidencia_langsmith.md).

| Archivo | Qué muestra |
|---|---|
| `langsmith_proyecto.png` | Lista de trazas del proyecto con la latencia de cada ejecución y el panel de estadísticas: 661 trazas, 1.818.261 tokens, USD 0,23, latencia P50 1,58 s y P99 11,19 s. |
| `langsmith_traza_citas.png` | Traza `secop-assistant` expandida: `get_process` (servidor MCP), `search_tender_documents` (RAG), tokens por llamada a `claude-haiku-5-5` y respuesta final con `[fuente: 01_EDP_545_2022.pdf, p. 1, §1 Información general del proceso]`. |
| `langsmith_traza_no_lo_se.png` | Traza de la pregunta sobre el seguro de vida del gerente: las búsquedas devuelven `{"found": false}` y la respuesta empieza por «No lo sé». |
| `langsmith_experimentos.png` | Vista *Compare* de B-claude, A-claude y C-local: corrección, precisión de fuente y abstención, y las respuestas lado a lado. Tokens y coste salen en cero porque los experimentos se publicaron desde checkpoints; el consumo real está en las trazas originales. |

No contienen claves ni paneles de credenciales.
