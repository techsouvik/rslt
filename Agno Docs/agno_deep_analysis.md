# Agno 2.6.9 — Complete Deep Analysis
**Analyzed:** 2026-06-04 | **Tool:** codegraph CLI (SQLite/FTS5) + direct source reads  
**Package:** `venv/Lib/site-packages/agno` (LBM project venv)  
**codegraph:** 853 files · 17,055 nodes · 48,446 edges  
**Subsystem files:** `docs_and_specs/agno_analysis/01–08_*.md` (full detail + file:line citations)

---

## Quick-Reference Index

| # | Subsystem | File | Key surprise |
|---|---|---|---|
| 1 | Core agent loop + streaming | `01_core_agent_streaming.md` | 37 event types; 17-section system prompt; memory extracted in background |
| 2 | Models + Gemini | `02_models_gemini.md` | Builtin tools disable all function tools; thinking_budget=0 blocks output |
| 3 | Tools | `03_tools.md` | 152 built-in tool files; show_tool_calls is 3 separate mechanisms |
| 4 | Teams + Workflows | `04_team_workflow.md` | 4 team modes (not 3); routing is tool-call driven |
| 5 | Knowledge + Memory + VectorDB | `05_knowledge_memory_vectordb.md` | MemoryManager is stateless; 19 VectorDB backends; memory extraction async |
| 6 | Evals + Culture + Learn + Guardrails | `06_eval_culture_learn_guardrails.md` | LearningMachine NOT wired into Agent; PromptInjection is keyword-only |
| 7 | Agent OS + API + JWT + Registry | `07_os_api_jwt_registry.md` | AgentOS is a FastAPI builder; Registry is in-memory; 3-layer JWT auth |
| 8 | Hooks + Compression + Skills + Scheduler + Reasoning | `08_hooks_compression_skills_scheduler.md` | Compression targets tool results not history; Skills are not callable |

---

## 1. Core Agent Loop & Streaming

### Entry points (`agent/agent.py`, `agent/_run.py`)

`Agent.run()` and `Agent.arun()` are thin wrappers that delegate entirely to `_run.run_dispatch()` / `_run.arun_dispatch()`. `run_dispatch` performs **14 pre-run steps** before entering `_run()` (non-streaming) or `_run_stream()` (streaming). The pre-read session optimization avoids a double DB round-trip on the first turn.

### The run loop (`agent/_run.py:324` / `:715`)

Both `_run()` and `_run_stream()` follow a **16-step sequence**. Background futures for memory, learning, and culture are launched at **step 7** — before the model is called — and joined at the end. The retry wrapper (`agent.retries` attempts) wraps the entire sequence. `RunCancelledException`, guardrail errors, and `KeyboardInterrupt` bypass retry.

### System prompt assembly (`agent/_messages.py:106`)

**17 named sections**, assembled in order:
1. description → 2. role → 3. instructions → 4. model instructions → 5. datetime/location →  
6. tool instructions → 7. expected output → 8. additional context → 9. skills →  
10. **memories** → 11. **cultural knowledge** → 12. session summary → 13. learnings →  
14. knowledge search instructions → 15. model suffix → 16. JSON output prompt → 17. session state

State variable substitution via `string.Template.safe_substitute()` on `{var_name}` patterns from `session_state`, `dependencies`, `metadata`, `user_id`.

### Tool execution chain

Three-layer: `model.response()` inner `while True:` loop → `run_function_calls()` → `FunctionCall.execute()`.

Tool stops loop when: `stop_after_tool_call`, `requires_confirmation`, `external_execution`, `requires_user_input`, or propagated `run_response.requirements` — all `break` the inner loop.

Arguments injected by name AND type hint — `my_agent: Agent` patterns work.

### Streaming events (`run/agent.py:143–558`)

**37 event types** in `RunOutputEvent` union:
- `stream=True` always yields `RunContentEvent` chunks
- `stream_events=True` additionally yields all lifecycle events: `ModelRequestStarted`, `ModelRequestCompleted` (with token counts), `ToolCallStarted`, `ToolCallCompleted`, `MemoryUpdateStarted`, `MemoryUpdateCompleted`, `RunStarted`, `RunCompleted`, etc.
- `yield_run_output=True` yields the final `RunOutput` object at stream end

### Cancellation (`run/cancel.py`)

Global `InMemoryRunCancellationManager` (swappable for Redis). `raise_if_cancelled()` polled at **5 points** in each run. Always cleaned up in `finally`.

### RunContext (`run/base.py:16`)

Carries: `run_id`, `session_id`, `user_id`, `session_state`, `dependencies`, `knowledge_filters`, `metadata`, `output_schema`, and a live `messages` reference (shallow-copied for tool hooks to prevent list corruption).

---

## 2. Models & Gemini Integration

### Base `Model` ABC (`models/base.py`)

Four required abstract methods: `invoke`, `ainvoke`, `invoke_stream`, `ainvoke_stream`. Full retry/cache/tool-call-loop infrastructure is in the base. Gemini-specific: `finally` blocks close/null the client after every call.

### Gemini class (`models/google/gemini.py`, 2079 lines)

**Critical rules (confirmed from source):**

| Rule | Source |
|---|---|
| `thinking_budget=0` blocks output — must be `> 0` to enable thinking | `gemini.py:reasoning/` |
| Gemini 2.5+ requires `thinking_level`, NOT `temperature`/`top_p`/`top_k` | config handling |
| Builtin tools (`google_search`, `file_search`, code_execution) **completely disable** external function tools | `gemini.py:398-401` |
| `grounding=True` is legacy — use `search=True` | explicit warning in code |
| Thought signatures are base64-encoded, stored in `provider_data`, re-attached per Part for multi-turn thinking continuity | streaming handler |

**Key Gemini params (all 40+):** generation config (`temperature`, `top_p`, `top_k`, `max_output_tokens`, `candidate_count`, `stop_sequences`, `presence_penalty`, `frequency_penalty`, `seed`, `response_logprobs`, `logprobs`), thinking config (`thinking_budget`, `thinking_level`), safety settings, system instruction, tool config (`function_calling_config`, `allowed_function_names`), grounding (`search`, `grounding`, `url_context`), file search (`file_search`), code execution (`code_execution`), client config (`api_key`, `base_url`, `project`, `location`, `vertexai`, `credentials`).

### Structured output (`agno/utils/gemini.py`)

`prepare_response_schema` triggers Pydantic→Gemini `Schema` conversion. `Dict[str, T]` fields use a synthetic `example_key` placeholder. Circular references are handled. Activated by `response_model` on Agent.

### Streaming

Cumulative token counts per chunk. `collect_metrics_on_completion=True` (default) reads only from final chunk (when `finish_reason` is set).

---

## 3. Tools System

### Base classes (`tools/function.py:132`, `tools/toolkit.py:12`)

`Function` is a Pydantic model with **25+ fields**: `name`, `description`, `parameters`, `entrypoint`, `async_entrypoint`, `return_type`, `cache_results`, `cache_ttl`, `cache_dir`, `stop_after_tool_call`, `requires_confirmation`, `requires_user_input`, `external_execution`, `show_result`, `run_in_background`, `enabled`, and more.

`Toolkit` is a plain class with `functions`/`async_functions` dicts, `register()`, `_register_decorated_tool()`, `connect()`/`close()` lifecycle hooks.

### `@tool` decorator (`tools/decorator.py:87`)

All kwargs: `name`, `description`, `cache_results`, `cache_ttl`, `stop_after_tool_call`, `requires_confirmation`, `requires_user_input`, `external_execution`, `show_result`, `run_in_background`. HITL flags (`requires_confirmation`, `requires_user_input`, `external_execution`) are **mutually exclusive**. Auto-detects async. Auto-sets `show_result=True` when `stop_after_tool_call=True`.

### Tool registration on Agent (`agent/_tools.py:340`, `parse_tools()`)

Handles 4 input types: `dict` / `Toolkit` / `Function` / `callable`. Strict mode propagated. `agent.tool_hooks` override. `_format_tools()` sorts for cache stability.

### Dispatch path

```
model.response() → while True loop
  → run_function_calls()
    → run_function_call()
      → FunctionCall.execute()
```

### Built-in tool categories (~152 files, ~15 categories)

`airflow`, `arxiv`, `aws`, `browser`, `calculator`, `csv`, `dalle`, `discord`, `duckdb`, `exa`, `firecrawl`, `github`, `gmail`, `googledrive`, `googlesearch`, `jira`, `linear`, `mcp`, `newspaper`, `notion`, `openbb`, `pandas`, `perplexity`, `postgres`, `pubmed`, `python`, `qdrant`, `reddit`, `resend`, `shell`, `slack`, `snowflake`, `spider`, `sql`, `stripe`, `tavily`, `telegram`, `todoist`, `twilio`, `twitter`, `wikipedia`, `yfinance`, `youtube`, `zendesk`, and more.

### MCP integration (`tools/mcp/mcp.py:29`)

Three transport modes: `stdio`, `sse`, `streamable_http`. `build_tools()` flow: connect → list_tools → wrap as `Function`. `header_provider` enables per-run auth. `MultiMCPTools` aggregates multiple servers. `skip_entrypoint_processing=True` for custom tool wrappers.

### `cache_results`

Filesystem cache with MD5 key, TTL check, generator results excluded. Key from function name + serialized args.

### Tool visibility (`show_tool_calls`)

No single flag — controlled via:
1. `show_result=True` on Function — content surfaced inline in response
2. `stream_events=True` on run — yields `ToolCallStartedEvent`/`ToolCallCompletedEvent`
3. Debug logging via `get_call_str()`

---

## 4. Teams & Workflows

### Team modes (`team/mode.py:6-22`)

**Four modes** (docs often only mention three):

| Mode | Behavior |
|---|---|
| `route` | Leader routes to one member; `respond_directly=True` for pass-through |
| `coordinate` | Default; leader delegates, synthesizes from all member responses |
| `broadcast` | `delegate_to_all_members=True` — every member gets every task |
| `tasks` | Autonomous iterative loop with task management tools (`create_task`, `assign_task`, `mark_all_complete`); loops up to `max_iterations=10` |

### Routing mechanism

Entirely **tool-call driven**. Leader LLM calls `delegate_task_to_member(member_id, task)` (a generator function in `team/_default_tools.py:538`). Member selection is by `member_id` string match. LLM knows members from system prompt XML listing built by `get_members_system_message_content`.

### session_state in teams

Members receive a `copy()` of `run_context.session_state`. After each delegation the copy is merged back via `merge_dictionaries` (`team/_default_tools.py:532`). **There is no `team_session_state`** — that name no longer exists.

### Streaming

`stream_member_events=True` (default) propagates member events upstream with `parent_run_id` set. `yield_run_output=True` used internally to capture full `RunOutput` from member stream.

### Workflows (`workflow/workflow.py`)

`Workflow._execute` (:1946) iterates steps sequentially, passing `previous_step_outputs` to each step via `StepInput`. Media accumulates across steps.

**`session_state` persistence**: Loaded from `session.session_data["session_state"]` at run start, merged with call-time state (DB wins by default), stripped of ephemeral keys, upserted to DB in `finally` block.

**28 `WorkflowRunEvent` types** covering: workflow lifecycle, step lifecycle, loop iterations, parallel execution, conditions, router, and HITL pauses.

**`Step`** (`workflow/step.py:72`) accepts exactly one of: `agent`, `team`, `executor` callable, or nested `workflow`. Full HITL per-step via `requires_confirmation`, `requires_user_input`, `requires_output_review`, `on_error=pause`.

### factory/ (`factory/base.py:21`)

`BaseFactory[T]` — per-request component builder for AgentOS. Required: `id` (API URL handle), `db`, `factory` callable. Used to create Agent/Team/Workflow with per-request context injection.

---

## 5. Knowledge, Memory & VectorDB

### Knowledge (`knowledge/knowledge.py:42`)

`Knowledge` is a `@dataclass` with two storage handles: `vector_db` (embeddings) and `contents_db` (metadata/status). `__post_init__` auto-creates the VectorDB collection. `isolate_vector_search=True` injects a `linked_to` metadata filter so multiple Knowledge instances can safely share one VectorDB collection.

**19 readers:** PDF, CSV, Docx, Excel, PPTX, JSON, Markdown, Text, Website, Firecrawl, Tavily, WebSearch, Arxiv, Wikipedia, YouTube, LLMs.txt, Docling, S3, FieldLabeledCSV. Accessed via `ReaderFactory`.

**8 chunking strategies:** `DocumentChunker`, `FixedSizeChunker`, `RecursiveChunker`, `MarkdownChunker`, `SemanticChunker`, `AgenticChunker`, `CodeChunker`, `RowChunker`. Default chunk_size 5000 for most. `AgenticChunker` uses `max_chunk_size`; `RowChunker` has no size/overlap.

**18 embedders:** All major providers + local (vLLM, Ollama, SentenceTransformer, FastEmbed).

### Memory (`memory/manager.py:45`)

`MemoryManager` is **stateless** — no in-process cache. All reads/writes go through `self.db`. Default model: `gpt-4o`.

**Memory injection**: `_messages.py:287` injects `<memories_from_previous_interactions>` block into system prompt when `add_memories_to_context=True`.

**Memory extraction**: Runs **in background after response** — either `asyncio.create_task` or `ThreadPoolExecutor.submit` — guarded by `update_memory_on_run=True` and `not enable_agentic_memory`. Does NOT block the response.

**`optimize_memories`**: Collapses all user memories into one via LLM call (SummarizeStrategy, `memory/strategies/summarize.py`). Writes back if `apply=True`.

**`create_session_summary`** (`session/summary.py:227`): Summarizes `session.get_messages(last_n_runs, limit)` into `SessionSummary(summary, topics)`. Injected into next run's system prompt under `<summary_of_previous_interactions>`.

### VectorDB (`vectordb/`)

**19 backends:** PgVector, Qdrant, ChromaDB, Milvus, MongoDB, LanceDB, Redis, Cassandra, ClickHouse, Couchbase, SingleStore, SurrealDB, Upstash, Weaviate, LangChain wrapper, LlamaIndex wrapper, LightRAG, plus abstract base.

Base interface mandates: `create`, `insert`, `upsert`, `search`, `async_search`, `drop`, `delete_by_*`, `content_hash_exists`, `get_supported_search_types`.

Distance metrics: `cosine`, `l2`, `max_inner_product`. All normalized to [0.0, 1.0] by `vectordb/score.py`.

Search types: `vector`, `keyword`, `hybrid`. Hybrid fusion: Qdrant uses RRF/DBSF; PgVector uses `vector_score_weight` float blend.

`similarity_threshold` on `VectorDb.__init__` provides a global min-score filter.

### Session (`session/agent.py:15`)

`AgentSession` dataclass: `session_id`, `agent_id`, `user_id`, `workflow_id`, `session_data` (blob), `runs` (list of `RunOutput`), `summary`.

`session_data` blob holds: `session_name`, `session_state` (persistent KV), `session_metrics`, images/videos/audio.

**12 session storage backends:** SQLite, Postgres, MySQL, MongoDB, DynamoDB, Firestore, Redis, SurrealDB, SingleStore, in-memory, JSON, GCS JSON.

---

## 6. Evals, Culture, Learn & Guardrails

### Evals (`eval/`)

Two separate eval roles:

**Standalone runners** — called externally, have own `.run()` / `.arun()`, persist to DB via `EvalRunRecord`:
- `AccuracyEval` — correctness scoring
- `AgentAsJudgeEval` — binary and numeric (1-10) scoring modes; `on_fail` callback; single and batch cases
- `PerformanceEval` — uses `tracemalloc` for memory measurement; p95 stats
- `ReliabilityEval` — no additional LLM call; pure structural tool-call verification with partial argument matching

**`BaseEval` as hook** — abstract `pre_check`/`post_check` for inline per-invocation eval via `Agent.post_hooks`.

### Culture (`culture/`)

No YAML format — culture is DB-stored `CulturalKnowledge` objects.

**Three integration modes:**
1. Read-only context injection (`add_culture_to_context`) — injected into system prompt (section 11)
2. Agentic contribution via tool
3. Post-run automatic extraction (`update_cultural_knowledge`) — uses a direct `model.response()` call (not an Agent) with tools `add_knowledge`, `update_knowledge`, `delete_knowledge`, `clear_knowledge`

### Learn (`learn/`)

`LearningMachine` is a facade over **6 typed stores**. **NOT natively wired into Agent** — must be called manually or via hooks.

**4 LearningModes:** `ALWAYS`, `AGENTIC`, `PROPOSE`, `HITL`.

**Store types:**
- `LearnedKnowledgeStore` — vector-backed; reusable cross-user insights (searchable)
- `UserMemoryStore` — per-user DB-backed observations
- `FeedbackConfigStore`, `SelfImprovementConfigStore` — config stubs, not yet implemented

Key distinction: `LearnedKnowledge` = reusable cross-user insights (vector search); `UserMemory` = per-user unstructured observations (DB lookup).

### Guardrails (`guardrails/`)

**Input-only** — no output guardrail types.

| Guardrail | Mechanism |
|---|---|
| `PIIDetectionGuardrail` | Mask-in-place (mutates `run_input.input_content`) or block mode; supports multimodal |
| `PromptInjectionGuardrail` | **Keyword-based** (17 patterns, **no LLM**) |
| `OpenAIModerationGuardrail` | OpenAI Moderation API; supports multimodal (image+text) |

Integration: guardrails execute **synchronously** before all other hooks, even in background-hook mode. `deepcopy` of args happens after the guardrail loop so PII masking mutations propagate correctly.

---

## 7. Agent OS, API, JWT & Registry

### Agent OS (`os/`)

`AgentOS` is a **FastAPI builder, not a process manager**. Initialization: `_initialize_agents` → `_initialize_teams` → `_initialize_workflows` → `_populate_registry` → duplicate-ID check → optional tracing + telemetry.

Lifespan chain composed recursively: user lifespan → MCP tools → db provisioning → scheduler → httpx cleanup.

`resync(app)` supports hot-reload (used by Studio).

### API server (`os/routers/`)

**19 router families.** Agents/teams/workflows use **form data** (not JSON) for run endpoints.

Two SSE streaming modes:
- **Inline**: client disconnect cancels the agent run
- **Resumable background**: agent survives disconnect; events buffered for reconnect

Features requiring a DB (components, schedules, approvals, registry) return `503` stubs when no DB is provided.

### JWT & Authentication (3-layer)

1. **`JWTValidator`** — standalone class
2. **`JWTMiddleware`** — Starlette middleware; full RBAC with **60+ endpoint scope mappings**
3. **`get_authentication_dependency`** — fallback security-key check at router level

Key resolution: param → `JWT_VERIFICATION_KEY` env → JWKS file param → `JWT_JWKS_FILE` env.

**RBAC is opt-in**: `authorization=True` activates scope enforcement.

**User isolation** (`user_isolation=True`): separate opt-in that gates non-admin callers to their own JWT `sub` on DB reads/writes.

Internal scheduler token uses `hmac.compare_digest` + fixed `INTERNAL_SERVICE_SCOPES`.

### `client/AgentOSClient`

Plain HTTP client; no built-in API key management — tokens passed per-call as `headers`. Uses shared `httpx` connection pools. SSE streaming via `_astream_post_form_data` + `_parse_sse_events`.

### `registry/Registry`

**Pure in-memory dataclass; not DB-backed.** Used to rehydrate Workflow steps (tools, functions, agents, teams) loaded from the database. `AgentOS._populate_registry()` auto-populates from all code-defined agents/teams. `GET /registry` serves its contents as JSON metadata.

### `remote/BaseRemote`

Supports two protocols: `"agentos"` (proprietary REST) and `"a2a"` (Agent-to-Agent JSON-RPC/REST). Config is TTL-cached (default 5 min). `RemoteDb` and `RemoteKnowledge` are thin proxy objects delegating to `AgentOSClient`.

---

## 8. Hooks, Compression, Skills, Scheduler, Reasoning & Supporting Systems

### Hooks (`hooks/`)

**Two lists on Agent**: `pre_hooks` / `post_hooks`.

`@hook(run_in_background=True)` decorator queues hooks into FastAPI `BackgroundTasks` (AgentOS only).

Arguments filtered by the hook's **own signature** — hooks don't need to accept all arguments.

**Raising `InputCheckError` / `OutputCheckError` blocks the run.** All other exceptions are swallowed. Async hooks only work in `arun()`. Guardrail hooks (BaseGuardrail/BaseEval) always run synchronously even in background mode.

Available hook contexts: `RunContext`, `RunInput`, `RunOutput`, `Agent`, `session_state`.

### Compression (`compression/`)

**Compresses tool result messages, NOT conversation history** — this is the opposite of what most harnesses do.

**Two triggers:**
- Count-based: `compress_tool_results_limit` (default 3 tool results)
- Token-based: `compress_token_limit`

Uses a separate LLM; async version runs parallel compression via `asyncio.gather`. Compressed text stored in `Message.compressed_content`; original preserved. Metrics tracked under `ModelType.COMPRESSION_MODEL`.

### Skills (`skills/`)

**Filesystem-based "domain expertise packages"** — NOT callable functions.

Each skill folder requires `SKILL.md` (YAML frontmatter + instruction body). Optional: `scripts/`, `references/`.

Three tools injected into agent: `get_skill_instructions`, `get_skill_reference`, `get_skill_script`.

The **agent explicitly loads skills when needed** — they are not automatically invoked. `AgentSkills` manages multiple loaders.

### Scheduler (`scheduler/`)

**DB-backed, HTTP-executed** job scheduler.

Components:
- `ScheduleManager` — CRUD for schedule records
- `SchedulePoller` — polls DB at configurable interval (default 15s); claims schedules via distributed lock
- `ScheduleExecutor` — makes HTTP calls to AgentOS endpoints with retry logic

Uses `croniter` for 5-field cron parsing + `pytz` for timezone. Auto-disables schedules on cron parse failure.

Requires: `pip install agno[scheduler]`.

### Reasoning (`reasoning/`)

**Two modes:**

1. **Native** (model returns thinking directly) — DeepSeek, Anthropic, OpenAI o-series, Gemini 2.5+, Vertex, Groq, Ollama, Azure AI Foundry
2. **Default CoT** — explicit reasoning agent with `ReasoningSteps` structured output

`ReasoningStep` fields: `title`, `action`, `result`, `reasoning`, `next_action`, `confidence`.

Full streaming support for all providers.

**Gemini-specific**: `thinking_budget=0` explicitly disables thinking; must be `> 0`.

### Approval (`approval/`)

**Two types:**
- `required` — blocking; run pauses until resolved via API
- `audit` — non-blocking audit trail

`@approval` composes with `@tool` in either order. `audit` requires at least one HITL flag already set. HITL flags (`requires_confirmation`, `requires_user_input`, `external_execution`) are **mutually exclusive**.

### Tracing (`tracing/`)

OTel + OpenInference instrumentation. Single call to `setup_tracing(db=...)` enables automatic tracing for all subsequent agent/team/workflow runs.

Custom `DatabaseSpanExporter` writes to Agno's own DB.

**Span types:** AGENT, TEAM, WORKFLOW, LLM, TOOL — derived from `openinference.span.kind` + `agno.team.id` attribute. LLM spans carry `llm.token_count.prompt/completion`.

### Metrics (`metrics/`)

**Hierarchy:** `BaseMetrics → RunMetrics` (per run) → `SessionMetrics` (per session).

**10 ModelType enum roles:** `MODEL`, `REASONING_MODEL`, `COMPRESSION_MODEL`, `MEMORY_MODEL`, and 6 more.

`RunMetrics.details` is `Dict[ModelType, List[ModelMetrics]]` — per-provider token breakdown.

`RunMetrics + RunMetrics` merges by `(model_type, provider, id)`.

**No separate `AgentMetrics`** — `RunMetrics` is the canonical object on `RunOutput.metrics`.

---

## Critical Cross-Cutting Facts

Things that are commonly misunderstood or not in the docs:

1. **Gemini builtin tools disable function tools entirely** — `search=True` or `file_search=True` means no external tools will be called, ever. This is enforced at `gemini.py:398-401`.

2. **`thinking_budget=0` blocks all output** on Gemini — it doesn't just disable thinking, it prevents any tokens from being generated. Must be `> 0` or omitted.

3. **Team routing is done by the LLM** via `delegate_task_to_member` tool call — the leader literally generates a function call to route. This means the LLM must produce a valid `member_id` string from its context.

4. **`LearningMachine` is not wired into Agent** — calling `agent.run()` does NOT automatically learn from the run. You must call `learning_machine.run(...)` separately or hook it in via `post_hooks`.

5. **Memory extraction is async/background** — it does NOT slow down the response. The response is returned to the caller while memory extraction runs in a thread/task.

6. **`MemoryManager` is stateless** — every call reads from and writes to the DB. There is no in-process memory cache. If your DB is slow, memory reads/writes are slow.

7. **Agno run endpoints use form data, not JSON** — `-F message="..."` in curl, `data={"message": "..."}` in requests, `-Form @{message="..."}` in PowerShell.

8. **`session_state` in teams has no separate namespace** — members share the same `session_state` dict (with a copy + merge pattern). There is no `team_session_state`.

9. **PromptInjectionGuardrail is keyword matching** — 17 hardcoded patterns, no LLM. It will miss sophisticated injections and will false-positive on legitimate prompts containing those keywords.

10. **Compression targets tool results, not conversation history** — it compresses large tool outputs, not the full message history. To compress history, use a summarization step or custom hook.

11. **`Registry` is in-memory only** — it is not persisted to the database. It is populated from code-defined agents/teams at startup and used only to rehydrate workflow steps.

12. **Skills are not tools** — skills are loaded explicitly by the agent when it calls `get_skill_instructions`. They do not appear in the LLM's tool list.

13. **`grounding=True` is deprecated** — use `search=True` for Google Search grounding. The legacy flag still works but logs a warning.

14. **RBAC and user isolation are both opt-in** — `AgentOS()` with no flags has no access control. `authorization=True` enables scope-based RBAC; `user_isolation=True` gates per-user data access.

---

## LBM-Specific Guidance

### What LBM uses / should use

| LBM component | Agno mechanism | Notes |
|---|---|---|
| Agents (research, plan, synth) | `Agent` with `run()` / `arun()` | Use `stream_events=True` for LBM streaming channel |
| BSV gathering harness | `Team` in `coordinate` mode or `Workflow` | Workflow gives session_state persistence between steps |
| session_state persistence | Workflow `session_state` + DB | session_state merged at end of every workflow run |
| LBM tool calls (Memgraph, Mongo) | `@tool(cache_results=True)` Toolkits | cache_results for idempotent graph queries |
| Gemini calls | `Gemini` with `thinking_level` not `temperature` | Never use temperature with Gemini 2.5+ |
| Structured extraction | `response_model=PydanticModel` + `structured_outputs=True` | Triggers Gemini response_schema; never free-text JSON |
| Memory injection | `Agent.memory` + `MemoryManager` | Memory is injected in section 10 of system prompt |
| Post-run learning | `LearningMachine` via `post_hooks` | NOT automatic — must be explicitly called |
| Eval runner | `AgentAsJudgeEval` or `ReliabilityEval` | ReliabilityEval has no extra LLM call — cheapest |
| Culture / persona | `culture/` DB-stored `CulturalKnowledge` | Add post-run extraction hook |
| Hooks for BSV veto | `pre_hooks` raising `InputCheckError` | Synchronous guardrail pattern |
| Context compression | `compression/` targeting tool results | Default 3-tool threshold; tune with `compress_token_limit` |
| Cron workflows | `scheduler/` DB-backed + AgentOS | Requires `pip install agno[scheduler]` |
| Knowledge search | `AgentKnowledge` + VectorDB | Use `isolate_vector_search=True` when sharing one collection |

### The 14 pre-run steps summary

Most LBM bugs in the agent loop come from assumptions about ordering. The pre-run steps (before model is called) include: session load, memory load, knowledge load, history load, context assembly, system prompt build, memory background task launch, model preparation. Only after all 14 does the model get called.

### session_state access pattern (correct)

```python
# In a workflow step:
def run(self, message, **kwargs):
    state = self.session_state  # loaded from DB at workflow start
    state["last_bsv"] = bsv_id
    # session_state is auto-saved to DB at end of workflow run
```

In an agent: `run_context.session_state` — but this is NOT auto-persisted unless using Workflow or AgentOS with a DB.

---

## Codegraph Stats per Subsystem

| Subsystem | Key symbols (codegraph nodes) |
|---|---|
| agent/ | Agent class, run_dispatch, _run, _run_stream, _messages, parse_tools, ~6,196 methods total |
| models/google/ | Gemini (2079 lines), ModelResponse, ToolExecution, prepare_response_schema |
| tools/ | Function, Toolkit, FunctionCall, @tool decorator, 152 built-in files |
| team/ | Team, TeamMode (4 values), delegate_task_to_member, merge_dictionaries |
| workflow/ | Workflow, Step, WorkflowRunEvent (28 types), StepInput |
| knowledge/ | Knowledge, 19 ReaderFactory readers, 8 chunkers, 18 embedders |
| memory/ | MemoryManager (stateless), SessionSummary, optimize_memories |
| vectordb/ | 19 backends, VectorDb base, score normalizer |
| eval/ | AccuracyEval, AgentAsJudgeEval, PerformanceEval, ReliabilityEval, BaseEval |
| culture/ | CulturalKnowledge, 3 integration modes |
| learn/ | LearningMachine, 6 stores, 4 LearningModes |
| guardrails/ | PII (mask/block), PromptInjection (17 keywords), OpenAIModeration |
| os/ | AgentOS (FastAPI builder), 19 router families, SchedulePoller |
| api/ | JWT 3-layer, 60+ RBAC scope mappings, resumable SSE |
| hooks/ | pre_hooks/post_hooks, @hook decorator, InputCheckError/OutputCheckError |
| compression/ | Tool result compression (NOT history), count+token triggers |
| skills/ | Filesystem packages, get_skill_instructions tool |
| scheduler/ | DB-backed HTTP scheduler, croniter, 15s poll interval |
| reasoning/ | Native + CoT modes, ReasoningStep (5 fields) |
| approval/ | required (blocking) + audit (non-blocking), HITL mutual exclusivity |
| tracing/ | OTel + OpenInference, DatabaseSpanExporter, 5 span types |
| metrics/ | RunMetrics, 10 ModelType roles, merge-by-key addition |
