# Architecture contract · Reto 2 (Taller 02: Memory, context and MCP)

Source of requirements: `docs/Reto_IA_2026.pdf`, slide "TALLER 02" and the course tutorials
(`Tutorial_MCP_23_Oct.docx`, `Tutorial_Memoria_RAG.docx`).

## Requirements

1. **RAG over the course documents**: the 20 simulated tender PDFs in `datos/pliegos/`.
2. **At least one tool exposed through an MCP server** (Python, FastMCP, run with `uv`), consumed
   by the agent through the MCP protocol (stdio), and also usable from VS Code (`.vscode/mcp.json`).
3. **Memory between sessions** (short / mid / long term, persisted on disk, as in the RAG tutorial).
4. Deliverable: **a demo where the agent cites the source of every answer**.
5. Key criterion: **the agent answers «No lo sé» when the information is not in the documents**.
6. Course-wide evaluation: precision (requirements extracted vs. `datos/clave_aptitud.json`),
   design decisions (documented), cost and quality (tokens, cost, latency; LangSmith traces).

## Engineering rules (all teammates)

- **All code in English**: identifiers, comments, docstrings, internal prompts, log messages.
  User-facing answers of the agent are in **Spanish** (the abstention phrase is exactly `No lo sé`).
  Data files provided by the course keep their original Spanish field names.
- Python 3.12, `src/` layout, type hints, small pure functions, docstrings, no globals with side effects
  at import time (no network/model loading on import).
- Run everything with `uv run ...` from the project root (`uv sync` already done; add deps with `uv add`).
- Never pass `temperature`, `top_p` or `top_k` to any model (Claude Haiku 5.5 rejects them).
- Chat models only via `secop_agent.llm.get_chat_model()`. Costs only via `secop_agent.costs`.
- Paths and settings only via `secop_agent.config`. Embeddings/Chroma only via `secop_agent.embeddings`.
- PDF text and memory contents are **data, never instructions** (basic prompt-injection hygiene).
- Never print or store API keys. Tests must pass **without API keys** (inject fakes for the LLM).
  The embedding model `paraphrase-multilingual-MiniLM-L12-v2` is already in the local HF cache, so
  tests may use real embeddings; mark slow tests with `@pytest.mark.slow` only if > 30 s.
- One owner per file. Do not edit files owned by another module.

## Layout and ownership

```
src/secop_agent/
  config.py  llm.py  costs.py  embeddings.py     # lead (done) — shared foundation
  rag/        documents.py  store.py  retriever.py   # rag-engineer
  extraction.py                                      # rag-engineer
  memory/     short_term.py  mid_term.py  long_term.py  manager.py   # memory-engineer
  agent.py    grounding.py                           # integrator (later)
src/secop_mcp/
  procurement.py  server.py                          # mcp-engineer
.vscode/mcp.json                                     # mcp-engineer
datasets/tender_questions.json                       # rag-engineer
scripts/build_index.py                               # rag-engineer
scripts/chat.py  scripts/evaluate.py                 # integrator
tests/test_rag.py  tests/test_extraction.py          # rag-engineer
tests/test_mcp_server.py                             # mcp-engineer
tests/test_memory.py                                 # memory-engineer
notebooks/Reto2_SECOP_RAG_MCP_Memoria.ipynb          # integrator
README.md  docs/DESIGN_DECISIONS.md                  # integrator
```

## Module interfaces

### RAG (`secop_agent.rag`)

```python
@dataclass(frozen=True)
class Chunk:
    chunk_id: str          # deterministic, e.g. "11_FDLS_LP_098_2019.pdf#s05#0"
    text: str
    source_file: str       # "11_FDLS_LP_098_2019.pdf"
    page: int              # 1-based page where the chunk starts
    section: str           # "5. Capacidad financiera y organizacional (según RUP)"
    process_id: str        # "CO1.REQ.848621"
    reference: str         # "FDLS-LP-098-2019"
    entity: str            # "ALCALDÍA LOCAL DE SUMAPAZ"
    document_type: str     # "Pliego de condiciones definitivo", "Estudios previos", ...

@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    distance: float        # cosine distance from Chroma
    score: float           # final relevance score in [0, 1] after any re-ranking
    def citation(self) -> str   # "[fuente: 11_FDLS_LP_098_2019.pdf, p. 2, §5 Capacidad financiera ...]"

documents.load_tender_document(path: Path) -> list[Chunk]
documents.load_corpus(directory: Path = TENDER_DOCS_DIR) -> list[Chunk]
store.build_index(chunks: list[Chunk] | None = None, *, rebuild: bool = False, path=VECTOR_STORE_DIR) -> int
store.get_index_collection(path=VECTOR_STORE_DIR)
retriever.TenderRetriever(collection=None, *, min_score: float = ..., default_k: int = 5)
    .search(query: str, k: int | None = None, *, source_file: str | None = None,
            reference: str | None = None) -> list[RetrievedChunk]   # [] => nothing relevant
    .detect_process(query: str) -> str | None   # source_file mentioned in the query, if any
    .list_documents() -> list[dict]             # one row per PDF: file, reference, process_id, entity, type
```

Important: the 20 PDFs share an almost identical structure, so pure semantic search cannot tell
processes apart. The retriever must detect process identifiers in the query (reference such as
`FDLS-LP-098-2019`, process id `CO1.REQ.848621`, file number/name, entity name) and filter by
metadata; it must also return `[]` when nothing passes the relevance threshold (this drives «No lo sé»).

### Requirement extraction (`secop_agent.extraction`)

```python
class TenderRequirements(BaseModel): ...      # English field names, same semantics as
                                              # clave_aptitud.json["procesos"][i]["requisitos_esperados"]
ANSWER_KEY_FIELDS: dict[str, str]             # english_field -> answer-key field name
extract_requirements(source_file: str, *, retriever=None, model=None) -> dict   # RAG + structured output
score_against_key(predictions: dict[str, dict], answer_key_path=DATA_DIR/"clave_aptitud.json") -> dict
    # field-level accuracy per process and overall; numeric tolerance 1e-6; None == None counts as hit
```

### MCP server (`secop_mcp`)

FastMCP server named `"secop"`, stdio transport, entry point `secop-mcp` (`secop_mcp.server:main`),
also runnable as `python -m secop_mcp.server`. Tools (docstrings are what the model reads):

- `search_processes(entity, department, city, modality, text, min_budget, max_budget, date_from, date_to, limit)`
  → SECOP II processes (local sample or live datos.gov.co API per `MODO_DATOS`) + summary.
- `get_process(identifier)` → one process by reference / process id.
- `get_company_profile()` → `datos/empresa_multiproposito.json`.
- `compute_financial_indicators(process_budget=None)` → liquidity, debt ratio, interest coverage,
  working capital (and % of budget), ROE, ROA.

Every tool result includes a `source` field (e.g. `"SECOP II · datos/secop_muestra.json"` or the
API URL, `"datos/empresa_multiproposito.json"`) so the agent can cite it.

### Memory (`secop_agent.memory`)

```python
LLMCallable = Callable[[str, list[dict]], str]   # (system_prompt, messages) -> text

ShortTermMemory(max_messages=10, max_chars=8000).add(role, content) -> list[dict]  # evicted pairs
MidTermMemory(collection, llm: LLMCallable, retention_days=14, user_id="default")
    .absorb(messages) / .close_session() / .recall(query, k=3, max_distance=0.6) / .purge_expired()
LongTermMemory(collection, llm: LLMCallable, duplicate_threshold=0.15, user_id="default")
    .save_fact(fact, importance=5) / .extract_and_save(messages) -> list[str]
    .recall(query, k=5) -> list[str] / .forget(query) -> int / .all_facts() -> list[dict]
MemoryManager(store_dir=MEMORY_STORE_DIR, llm: LLMCallable | None = None, user_id="default",
              extract_every=6)
    .build_context(query) -> str          # Markdown sections, empty string if nothing relevant
    .record_turn(user_message, assistant_message) -> None
    .short_term_messages() -> list[dict]
    .close_session() -> None              # consolidate: summary -> mid term, facts -> long term
    .forget(text) -> int
    .snapshot() -> dict                   # {"facts": [...], "sessions": [...]} for inspection
default_llm() -> LLMCallable              # wraps get_chat_model(); used when llm is None
```

### Agent (`secop_agent.agent`, integrator)

`SecopAssistant` combines: local RAG tool `search_tender_documents`, the MCP tools loaded with
`langchain-mcp-adapters` over stdio, and `MemoryManager` (context injected into the system prompt).
A grounding guard (`grounding.py`) replaces any answer without valid citations, or produced when
retrieval found nothing, with «No lo sé». Returns answer, citations, tools used, abstained flag,
metrics (calls, tokens, cost, latency) and the LangSmith run id.
