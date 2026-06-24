# Agno 2.6.9 — Hooks, Compression, Skills, Scheduler, Reasoning & Supporting Systems
**Subsystems:** hooks/, compression/, skills/, scheduler/, reasoning/, approval/, tracing/, metrics/
**Codegraph:** 853 files, 17,055 nodes, 48,446 edges
**Analysis date:** 2026-06-04

---

## Table of Contents
1. [Hooks](#1-hooks)
2. [Compression](#2-compression)
3. [Skills](#3-skills)
4. [Scheduler](#4-scheduler)
5. [Reasoning](#5-reasoning)
6. [Approval (HITL)](#6-approval-hitl)
7. [Tracing](#7-tracing)
8. [Metrics](#8-metrics)

---

## 1. Hooks

**Files:** `hooks/__init__.py`, `hooks/decorator.py`, `agent/_hooks.py`

### 1.1 Hook Concept

Hooks are plain Python callables registered on an `Agent` via two lists:

```python
# agent/agent.py:183,185
pre_hooks:  Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]] = None
post_hooks: Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]] = None
```

Pre-hooks fire before the LLM receives input; post-hooks fire after the agent produces output. There are **no separate "pre/post LLM" or "pre/post tool" hook slots at the agent level** — those are tool-level hooks (see `@tool(pre_hook=..., post_hook=...)`).

### 1.2 The `@hook` Decorator

`hooks/decorator.py:56` — `@hook` is optional decoration for any callable added to `pre_hooks` / `post_hooks`. Without it, the callable works fine. With it, you gain the `run_in_background` flag:

```python
@hook(run_in_background=True)
def my_background_hook(run_output, agent):
    send_notification(run_output.content)

@hook(run_in_background=True)
async def my_async_background_hook(run_output, agent):
    await send_async_notification(run_output.content)
```

The decorator stamps `_agno_run_in_background = True` on the wrapper function (attribute `HOOK_RUN_IN_BACKGROUND_ATTR = "_agno_run_in_background"`). It handles `@hook`, `@hook()`, and `@hook(run_in_background=True)` forms. Async detection uses `inspect.iscoroutinefunction` + `inspect.unwrap` chain + CO_COROUTINE flag inspection.

### 1.3 Hook Registration on Agent

```python
agent = Agent(
    model=...,
    pre_hooks=[validate_input_hook],
    post_hooks=[log_output_hook, send_to_analytics_hook],
)
```

The agent also exposes `_run_hooks_in_background: Optional[bool] = None` (line 187) — a global flag that pushes ALL non-guardrail hooks into FastAPI `BackgroundTasks` when running under AgentOS.

### 1.4 Arguments Each Hook Receives

Hook arguments are **filtered dynamically** via `filter_hook_args` (`utils/hooks.py`) — the executor inspects the hook's signature and passes only the arguments it declares. Available argument pool:

**Pre-hooks** (`agent/_hooks.py:61-72`):
| Argument | Type | Description |
|---|---|---|
| `run_input` | `RunInput` | The user input being processed |
| `run_context` | `RunContext` | Full run context object |
| `agent` | `Agent` | The agent instance |
| `session` | `AgentSession` | Current session |
| `user_id` | `Optional[str]` | User identifier |
| `debug_mode` | `Optional[bool]` | Debug flag |
| `metadata` | `Optional[Dict]` | Run metadata |

**Post-hooks** (`agent/_hooks.py:280-290`):
| Argument | Type | Description |
|---|---|---|
| `run_output` | `RunOutput` | The completed run output |
| `run_context` | `RunContext` | Full run context object |
| `agent` | `Agent` | The agent instance |
| `session` | `AgentSession` | Current session |
| `user_id` | `Optional[str]` | User identifier |
| `debug_mode` | `Optional[bool]` | Debug flag |
| `metadata` | `Optional[Dict]` | Run metadata |

### 1.5 How Hooks Can Block or Modify Execution

- **Blocking (guardrail mode):** Pre-hooks that raise `InputCheckError` or `OutputCheckError` (from `agno.exceptions`) are caught and **re-raised**, halting the run. This is how `BaseGuardrail` and `BaseEval` hooks gate execution.
- **Mutation:** Pre-hooks can mutate `run_input` in place; the final `run_input` is written back to `run_response.input` after all pre-hooks complete (line 150).
- **Non-blocking:** All other exceptions are caught and logged (`log_exception`) — hooks cannot accidentally crash the agent run.
- Hooks that raise `InputCheckError` or `OutputCheckError` in background mode are still executed **synchronously** (guardrails are never backgrounded).

### 1.6 Execution Order and Background Logic

`agent/_hooks.py` — key rules:
1. If `agent._run_hooks_in_background is True` and `background_tasks` is present (FastAPI context):
   - Guardrail hooks run **synchronously first**; all others are queued into `background_tasks.add_task`.
   - Arguments are deep-copied before queueing to prevent race conditions.
2. If individual hook has `@hook(run_in_background=True)`:
   - That specific hook is added to `background_tasks`; others run inline.
3. In sync `run()`: async hooks are **skipped with a warning** (line 122-125). Use `arun()` for async hooks.
4. In async `arun()`: both sync and async hooks are supported (line 231-235, awaited if async).

### 1.7 Tool-Level Hooks

Tools can have their own pre/post hooks via `@tool(pre_hook=..., post_hook=..., tool_hooks=[...])` — these run around individual tool executions and are defined in `tools/function.py`.

### 1.8 Stream Events

When `stream_events=True`, hook execution emits events:
- `PreHookStartedEvent` / `PreHookCompletedEvent`
- `PostHookStartedEvent` / `PostHookCompletedEvent`

These events are yielded from the run stream so UI clients can observe hook execution progress.

### 1.9 `session_state` in Hooks

`session_state` is accessible via `run_context.session_state` (the `RunContext` object carries it). Hooks that accept `run_context` can read and mutate session state freely since `RunContext` is passed by reference.

---

## 2. Compression

**Files:** `compression/__init__.py`, `compression/manager.py`

### 2.1 What Is Compressed

Compression in Agno is **not conversation-history summarization** — it compresses **tool result messages** (`role == "tool"`). The goal is to reduce the size of tool outputs (which can be large JSON blobs, web pages, etc.) stored in the message history, saving context window tokens on subsequent LLM calls.

### 2.2 `CompressionManager` Dataclass (`compression/manager.py:53`)

```python
@dataclass
class CompressionManager:
    model: Optional[Model] = None          # LLM used for compression
    compress_tool_results: bool = True
    compress_tool_results_limit: Optional[int] = None  # count-based trigger
    compress_token_limit: Optional[int] = None         # token-based trigger
    compress_tool_call_instructions: Optional[str] = None  # override default prompt
    stats: Dict[str, Any] = field(default_factory=dict)
```

Default behaviour (`__post_init__` line 62-64): if **neither** limit is set, `compress_tool_results_limit` defaults to `3` (compress when 3+ uncompressed tool results exist).

### 2.3 Trigger Conditions (`should_compress` / `ashould_compress`)

Two independent checks, either can trigger compression:

1. **Token threshold** (line 88-91): If `compress_token_limit` is set and `model.count_tokens(messages)` >= threshold → compress. Requires a model reference for counting.
2. **Count threshold** (line 95-101): Count of `role == "tool"` messages where `compressed_content is None` >= `compress_tool_results_limit` → compress.

`should_compress` is sync; `ashould_compress` is async (uses `await model.acount_tokens(...)`).

### 2.4 Compression Strategy

A single LLM call per tool result message. Default prompt (`DEFAULT_COMPRESSION_PROMPT`, lines 16-49) instructs the model to:
- **Preserve:** specific facts, numbers, statistics, entities, identifiers, temporal data, key quotes
- **Compress to essentials:** descriptions, explanations, lists
- **Remove entirely:** introductions, hedging language, meta-commentary, formatting artifacts, redundant content

The compressed output is stored in `Message.compressed_content`; the original `Message.content` is preserved. Subsequent rendering presumably uses `compressed_content` when available.

### 2.5 Async Parallel Compression

`acompress()` (line 247) uses `asyncio.gather(*tasks)` to compress all uncompressed tool results **in parallel** — significant speedup vs. serial sync version.

### 2.6 Statistics Tracking

After compression, `CompressionManager.stats` accumulates:
- `"tool_results_compressed"`: count of tool results compressed
- `"original_size"`: total character count before compression
- `"compressed_size"`: total character count after compression

For Gemini models that combine multiple tool calls in one message, `len(msg.tool_calls)` is used as the count rather than 1.

### 2.7 Metrics Integration

Both sync and async `_compress_tool_result` methods accumulate metrics into `RunMetrics` using `accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)`. This means compression LLM usage is tracked separately under the `"compression_model"` key in `RunMetrics.details`.

### 2.8 Integration with Agent Loop

`CompressionManager.compress` is called from `models/base.py` (2 callers). The agent passes messages + a `CompressionManager` instance to the model layer. The model layer calls `should_compress()` before building the request; if True, calls `compress()` which mutates the messages list in place (sets `compressed_content`).

### 2.9 LLM for Compression

Any `Model` subclass can be used. If `model` is None, `get_model()` is called (likely falls back to a default). A warning is logged and the original content is returned unchanged if no compression model is available.

---

## 3. Skills

**Files:** `skills/__init__.py`, `skills/skill.py`, `skills/agent_skills.py`, `skills/loaders/base.py`, `skills/loaders/local.py`, `skills/loaders/__init__.py`, `skills/validator.py`, `skills/errors.py`, `skills/utils.py`

### 3.1 What Skills Are

Skills are **packages of domain expertise injected into an agent as system-prompt knowledge + callable tools**. They differ from tools in that:
- Skills contain **markdown instructions** (prose guidance the agent reads)
- Skills contain **reference documents** (documentation files, cheatsheets)
- Skills contain **executable scripts** (code the agent can run via a tool call)
- Skills are **not directly callable** by the agent — they're accessed through three special tool functions

Skills live in the `Agent.skills` field (`agent/agent.py:160`): `skills: Optional[Skills] = None`.

### 3.2 `Skill` Dataclass (`skills/skill.py:6`)

```python
@dataclass
class Skill:
    name: str               # unique, lowercase, hyphens only (max 64 chars)
    description: str        # short description (max 1024 chars)
    instructions: str       # full SKILL.md body — what the agent reads
    source_path: str        # filesystem path to the skill folder
    scripts: List[str]      # filenames in scripts/ subdirectory
    references: List[str]   # filenames in references/ subdirectory
    metadata: Optional[Dict[str, Any]] = None
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
```

### 3.3 Skill Directory Format (Agent Skills Spec)

A skill is a folder containing:
```
my-skill/
    SKILL.md          # Required: YAML frontmatter + instruction body
    scripts/          # Optional: executable scripts
        run.py
    references/       # Optional: documentation files
        guide.md
```

`SKILL.md` YAML frontmatter allowed fields (`skills/validator.py:13`):
- `name`, `description`, `license`, `allowed-tools`, `metadata`, `compatibility`

### 3.4 Skill Loading

**`SkillLoader` ABC** (`skills/loaders/base.py:7`): abstract `load() -> List[Skill]`

**`LocalSkills`** (`skills/loaders/local.py:12`): concrete loader from filesystem.
- Takes `path` (single skill folder or directory of skill folders)
- Validates each skill against spec (raises `SkillValidationError` if invalid, unless `validate=False`)
- Parses YAML frontmatter via `yaml.safe_load` with fallback simple `key: value` parser
- Discovers scripts and references via directory iteration

**`AgentSkills`** (`skills/agent_skills.py:29`): registry that holds multiple loaders:
```python
agent_skills = AgentSkills(loaders=[LocalSkills("/path/to/skills")])
```
- Calls each loader's `load()` on init, stores by name (warns on duplicate names)
- `reload()` clears and re-loads all
- `get_skill(name)`, `get_all_skills()`, `get_skill_names()`

### 3.5 How Skills Compose with Agent

`AgentSkills.get_system_prompt_snippet()` generates an XML block injected into the system prompt listing available skills. `AgentSkills.get_tools()` returns three `Function` objects the agent can call:

| Tool | Signature | Purpose |
|---|---|---|
| `get_skill_instructions` | `(skill_name: str) -> str` | Load full instructions JSON |
| `get_skill_reference` | `(skill_name: str, reference_path: str) -> str` | Read a reference doc |
| `get_skill_script` | `(skill_name: str, script_path: str, execute: bool=False, args: List[str]=None, timeout: int=30) -> str` | Read or execute a script |

Path traversal attacks are prevented via `safe_join_relative_path` + `PathSecurityError`.

### 3.6 Discovery Workflow (Agent's Perspective)

1. Agent sees `<skills_system>` block in system prompt listing skill names + descriptions
2. Agent calls `get_skill_instructions(skill_name)` when a task matches
3. Agent optionally calls `get_skill_reference` for specific documentation
4. Agent optionally calls `get_skill_script(execute=True)` to run a script
5. References are **read-only documentation** — only `scripts/` files are executable

### 3.7 Validation Rules (`skills/validator.py`)

- Name: lowercase, alphanumeric + hyphens, max 64 chars, no leading/trailing/consecutive hyphens, must match directory name
- Description: non-empty string, max 1024 chars
- Compatibility: max 500 chars
- No unknown frontmatter fields (only the 6 in `ALLOWED_FIELDS`)

---

## 4. Scheduler

**Files:** `scheduler/__init__.py`, `scheduler/cron.py`, `scheduler/executor.py`, `scheduler/manager.py`, `scheduler/poller.py`, `scheduler/cli.py`

### 4.1 Architecture Overview

The scheduler is a DB-backed, HTTP-based job scheduler. Schedules are stored in the database; a poller claims due schedules and fires them by making HTTP calls to AgentOS endpoints.

Components:
- **`ScheduleManager`**: Pythonic CRUD API for schedules (direct DB, no HTTP)
- **`SchedulePoller`**: Async background loop that polls DB and fires executions
- **`ScheduleExecutor`**: Makes HTTP calls to AgentOS endpoints, handles retries
- **`cron.py`**: Cron expression validation and next-run computation

### 4.2 `Schedule` Data Model (`db/schemas/scheduler.py`)

Fields on a `Schedule`:
- `id`: UUID string
- `name`: human-readable identifier (unique)
- `description`: optional description
- `method`: HTTP method (default `"POST"`)
- `endpoint`: target path (e.g., `/v1/agents/{id}/runs`)
- `payload`: dict of form/JSON payload
- `cron_expr`: 5-field cron string (e.g., `"*/5 * * * *"`)
- `timezone`: TZ string (e.g., `"UTC"`, `"America/New_York"`)
- `timeout_seconds`: max execution time (default 3600)
- `max_retries`: retry count (default 0)
- `retry_delay_seconds`: delay between retries (default 60)
- `enabled`: bool
- `next_run_at`: epoch seconds for next execution
- `locked_by` / `locked_at`: distributed lock for claim-based execution

### 4.3 Cron Expression Support (`scheduler/cron.py`)

- Uses `croniter` library (requires `pip install agno[scheduler]`)
- Uses `pytz` for timezone support
- `validate_cron_expr(expr: str) -> bool`: validates 5-field cron
- `validate_timezone(tz: str) -> bool`: validates TZ string via pytz
- `compute_next_run(cron_expr, timezone_str="UTC", after_epoch=None) -> int`: returns epoch seconds with a **monotonicity guard** (always at least `now + 1`)

### 4.4 `ScheduleManager` CRUD (`scheduler/manager.py`)

Full sync + async API:
```python
manager = ScheduleManager(db=my_db)

# Create with conflict handling
schedule = manager.create(
    name="daily-report",
    cron="0 9 * * *",
    endpoint="/v1/agents/my-agent/runs",
    method="POST",
    payload={"message": "generate daily report"},
    timezone="America/New_York",
    timeout_seconds=3600,
    max_retries=2,
    retry_delay_seconds=120,
    if_exists="skip",   # "raise" | "skip" | "update"
)

# Async versions
await manager.acreate(...)
await manager.alist()
await manager.aenable(schedule_id)
await manager.adisable(schedule_id)
await manager.aget_runs(schedule_id, limit=20, page=1)
```

`ScheduleManager._call()` transparently handles sync vs. async DB by bridging via `ThreadPoolExecutor` when called from inside an async event loop (avoids `RuntimeError: no running event loop`).

### 4.5 `SchedulePoller` (`scheduler/poller.py`)

```python
poller = SchedulePoller(
    db=my_db,
    executor=my_executor,
    poll_interval=15,        # seconds between poll cycles
    worker_id="worker-abc",  # for distributed locking
    max_concurrent=10,       # max parallel in-flight executions
    stop_timeout=30,
)
await poller.start()   # starts asyncio background task
await poller.stop()    # graceful shutdown with task cancellation
await poller.trigger(schedule_id)  # immediate manual trigger
```

Poll loop: polls first, then sleeps (`_poll_loop`). Each poll claims all due schedules via `db.claim_due_schedule(worker_id)` in a tight loop until no more are due, spawning `asyncio.create_task` for each (up to `max_concurrent`).

### 4.6 `ScheduleExecutor` (`scheduler/executor.py`)

HTTP client backed by `httpx.AsyncClient`. For `/v1/agents|teams|workflows/{id}/runs` endpoints:
- Submits as `background=true` form request
- Polls the run until completion (`_background_run`)

For other endpoints:
- Simple JSON request/response (`_simple_request`)

Retry loop: up to `max_retries + 1` attempts with `retry_delay_seconds` sleep between. Statuses tracked: `"running"`, `"success"`, `"paused"`, `"failed"`, `"cancelled"`.

After execution, `compute_next_run()` advances `next_run_at`. If cron computation fails, the schedule is **auto-disabled** to prevent infinite failure loops.

### 4.7 Persistence

All schedule and run state is stored in the application DB (same Agno DB used for agents). DB methods required:
`get_schedule`, `get_schedule_by_name`, `get_schedules`, `create_schedule`, `update_schedule`, `delete_schedule`, `release_schedule`, `claim_due_schedule`, `create_schedule_run`, `update_schedule_run`, `get_schedule_run`, `get_schedule_runs`.

A `ScheduleRun` record is created at the start of each execution (status=`"running"`) and updated on completion/failure/cancellation.

---

## 5. Reasoning

**Files:** `reasoning/__init__.py`, `reasoning/step.py`, `reasoning/manager.py`, `reasoning/default.py`, `reasoning/helpers.py`, `reasoning/gemini.py`, `reasoning/anthropic.py`, `reasoning/openai.py`, `reasoning/deepseek.py`, `reasoning/groq.py`, `reasoning/ollama.py`, `reasoning/vertexai.py`, `reasoning/azure_ai_foundry.py`

### 5.1 Architecture

Two reasoning modes:

1. **Native reasoning**: The `reasoning_model` itself (DeepSeek, Anthropic Claude with extended thinking, OpenAI o1/o3, Gemini 2.5+, etc.) returns its chain-of-thought as part of the response. A thin agent wraps the model and extracts `reasoning_content` from the message.

2. **Default CoT reasoning**: An explicit reasoning agent (backed by any `reasoning_model`) runs a structured 6-step Chain-of-Thought process before the main agent's LLM call. Output is `ReasoningSteps` Pydantic model.

The `ReasoningManager` class (`reasoning/manager.py:106`) is the unified entry point for both.

### 5.2 `ReasoningConfig` (`reasoning/manager.py:77`)

```python
@dataclass
class ReasoningConfig:
    reasoning_model: Optional[Model] = None
    reasoning_agent: Optional[Agent] = None
    min_steps: int = 1
    max_steps: int = 10
    tools: Optional[List[...]] = None
    tool_call_limit: Optional[int] = None
    use_json_mode: bool = False
    telemetry: bool = True
    debug_mode: bool = False
    debug_level: Literal[1, 2] = 1
    run_context: Optional[RunContext] = None
    run_metrics: Optional[RunMetrics] = None
```

### 5.3 `ReasoningStep` Pydantic Model (`reasoning/step.py:14`)

```python
class ReasoningStep(BaseModel):
    title: Optional[str]           # concise step title
    action: Optional[str]          # "I will..." first-person action
    result: Optional[str]          # "I did this and got..." first-person result
    reasoning: Optional[str]       # thought process behind the step
    next_action: Optional[NextAction]  # continue | validate | final_answer | reset
    confidence: Optional[float]    # 0.0 to 1.0 confidence score

class ReasoningSteps(BaseModel):
    reasoning_steps: List[ReasoningStep]
```

`NextAction` enum: `CONTINUE`, `VALIDATE`, `FINAL_ANSWER`, `RESET`.

### 5.4 `ReasoningEvent` (`reasoning/manager.py:54`)

Events emitted during reasoning, unified across Agent and Team:
```python
@dataclass
class ReasoningEvent:
    event_type: ReasoningEventType   # started | content_delta | step | completed | error
    reasoning_content: Optional[str]  # delta for streaming
    reasoning_step: Optional[ReasoningStep]
    reasoning_steps: List[ReasoningStep]
    error: Optional[str]
    message: Optional[Message]        # for native reasoning
    reasoning_messages: List[Message]
```

### 5.5 Model Detection (`_detect_model_type`)

`ReasoningManager._detect_model_type(model)` returns a string key by checking class name and model ID:

| Key | Models Detected |
|---|---|
| `"deepseek"` | DeepSeek reasoning models |
| `"anthropic"` | Anthropic Claude with extended thinking |
| `"openai"` | OpenAI o1/o3/o4 |
| `"groq"` | Groq reasoning models |
| `"ollama"` | Ollama reasoning models |
| `"ai_foundry"` | Azure AI Foundry |
| `"gemini"` | Gemini 2.5+ / 3.x with thinking |
| `"vertexai"` | VertexAI |
| `None` | Not a native reasoning model |

### 5.6 Gemini Reasoning Detection (`reasoning/gemini.py:13`)

```python
def is_gemini_reasoning_model(reasoning_model: Model) -> bool:
    is_gemini_class = reasoning_model.__class__.__name__ == "Gemini"
    model_id = reasoning_model.id.lower()
    has_thinking_support = (
        "2.5" in model_id or "3.0" in model_id or "3.5" in model_id
        or "deepthink" in model_id or "gemini-3" in model_id
    )
    has_thinking_budget = (
        hasattr(reasoning_model, "thinking_budget")
        and reasoning_model.thinking_budget is not None
        and reasoning_model.thinking_budget > 0  # 0 EXPLICITLY DISABLES thinking
    )
    has_include_thoughts = hasattr(reasoning_model, "include_thoughts") and reasoning_model.include_thoughts is not None
    return is_gemini_class and (has_thinking_support or has_thinking_budget or has_include_thoughts)
```

**Critical rule:** `thinking_budget=0` explicitly disables thinking per Google API docs. Must be `> 0` to enable.

### 5.7 Gemini Reasoning Extraction

For native Gemini reasoning, the reasoning agent runs the messages through `reasoning_agent.run(input=messages)` and extracts `msg.reasoning_content` from returned messages. The content is wrapped as:
```python
Message(
    role="assistant",
    content=f"<thinking>\n{reasoning_content}\n</thinking>",
    reasoning_content=reasoning_content
)
```

### 5.8 Default CoT Reasoning Agent (`reasoning/default.py`)

When no native reasoning model is detected, `get_default_reasoning_agent` creates an `Agent` with:
- A detailed 6-step instruction set (Problem Analysis → Decompose → Intent → Execute → Validate → Final Answer)
- `output_schema=ReasoningSteps` (structured output, Pydantic model)
- `session_state`, `dependencies`, `metadata` forwarded from the parent `run_context`
- Min/max steps configurable (default 1–10)

### 5.9 Streaming Support

`stream_native_reasoning` / `astream_native_reasoning` yield `Tuple[Optional[str], Optional[ReasoningResult]]`:
- During streaming: `(reasoning_content_delta, None)`
- At end: `(None, ReasoningResult)`

Currently has full streaming support for: DeepSeek, Anthropic, Gemini, OpenAI, VertexAI, Azure AI Foundry, Groq, Ollama.

### 5.10 Metrics Propagation

Reasoning model metrics are accumulated into the parent `RunMetrics` under the `"reasoning_model"` key via `accumulate_eval_metrics(reasoning_agent_response.metrics, run_metrics, prefix="reasoning")`.

### 5.11 `ReasoningResult` (`reasoning/manager.py:95`)

```python
@dataclass
class ReasoningResult:
    message: Optional[Message]
    steps: List[ReasoningStep]
    reasoning_messages: List[Message]
    success: bool = True
    error: Optional[str] = None
```

---

## 6. Approval (HITL)

**Files:** `approval/__init__.py`, `approval/decorator.py`, `approval/types.py`

### 6.1 `ApprovalType` Enum (`approval/types.py`)

```python
class ApprovalType(str, Enum):
    required = "required"   # blocking: run pauses until approval resolved
    audit    = "audit"      # non-blocking: audit record created post-HITL
```

### 6.2 `@approval` Decorator (`approval/decorator.py`)

Marks a tool function as requiring human approval. Can be stacked with `@tool` in either order:

```python
# Order 1: @approval on top of @tool (Function already exists)
@approval
@tool(requires_confirmation=True)
def delete_record(id: str) -> str: ...

# Order 2: @approval below @tool (raw callable, sentinel stamped)
@tool
@approval(type="audit")
def read_sensitive_data(id: str) -> str: ...

# Short forms
@approval                         # type="required" default
@approval()                       # same
@approval(type="required")        # explicit
@approval(type="audit")           # non-blocking audit
```

**When `@approval` is above `@tool`** (receives a `Function`): directly sets `function.approval_type` and auto-sets `requires_confirmation=True` if no HITL flag is set.

**When `@approval` is below `@tool`** (receives a raw callable): stamps `_agno_approval_type = "required"` | `"audit"` sentinel on the raw function. `@tool` reads this sentinel during `Function` creation (`tools/decorator.py:214`).

### 6.3 HITL Flags (Mutually Exclusive)

Exactly one of these may be `True` simultaneously:
- `requires_confirmation`: agent pauses and waits for `confirmed=True/False` from user
- `requires_user_input`: agent pauses and presents input schema to user
- `external_execution`: tool is executed outside the agent context

### 6.4 `ToolExecution` HITL Fields (`models/response.py:28`)

```python
@dataclass
class ToolExecution:
    requires_confirmation: Optional[bool]
    confirmed: Optional[bool]
    confirmation_note: Optional[str]
    requires_user_input: Optional[bool]
    user_input_schema: Optional[List[UserInputField]]
    user_feedback_schema: Optional[List[UserFeedbackQuestion]]
    answered: Optional[bool]
    external_execution_required: Optional[bool]
    external_execution_silent: Optional[bool]
    approval_type: Optional[str]   # "required" | "audit"
    approval_id: Optional[str]     # ID of approval record created on pause

    @property
    def is_paused(self) -> bool:
        return bool(self.requires_confirmation or self.requires_user_input
                    or self.external_execution_required)
```

### 6.5 Blocking vs. Non-Blocking

- **`required`** (blocking): when `is_paused = True`, the agent run is suspended. The run can be continued via the AgentOS API by providing approval. The `approval_id` field links back to the approval record.
- **`audit`** (non-blocking): the HITL interaction resolves normally; an approval record is created afterward for compliance/logging. Does **not** pause the run.

### 6.6 `audit` Constraint

`@approval(type='audit')` requires at least one HITL flag to be set on `@tool()`. If none are set, a `ValueError` is raised at decoration time.

---

## 7. Tracing

**Files:** `tracing/__init__.py`, `tracing/setup.py`, `tracing/exporter.py`, `tracing/schemas.py`

### 7.1 Technology Stack

Agno tracing is built on **OpenTelemetry** + **OpenInference**:
- `opentelemetry-api`, `opentelemetry-sdk` — standard OTel
- `openinference-instrumentation-agno` — Agno-specific OTel instrumentor that auto-instruments all agent/team/workflow runs
- Install: `pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno`

### 7.2 Enabling Tracing (`tracing/setup.py:23`)

```python
from agno.tracing import setup_tracing
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="tmp/traces.db")
setup_tracing(
    db=db,
    batch_processing=False,        # True = BatchSpanProcessor (better perf)
    max_queue_size=2048,
    max_export_batch_size=512,
    schedule_delay_millis=5000,
)

# All subsequent agent runs are automatically traced
agent = Agent(...)
agent.run("Hello")   # produces spans
```

The function is idempotent (checks for existing `TracerProvider`, skips if already configured). Called from `os/utils.py` on AgentOS startup.

### 7.3 `DatabaseSpanExporter` (`tracing/exporter.py:18`)

Custom `SpanExporter` that writes to Agno's own database. On `export(spans)`:
1. Convert `ReadableSpan` → `Span` objects
2. Group by `trace_id`
3. For each group: `db.upsert_trace(trace)` + `db.create_spans(spans)`

Supports sync DB, async DB, and `RemoteDb` (remote skips — handles its own tracing). Async export is scheduled via `asyncio.create_task` when inside a running loop.

### 7.4 Data Models

**`Trace`** (`tracing/schemas.py:14`):
```
trace_id, name, status (OK/ERROR/UNSET), start_time, end_time,
duration_ms, total_spans, error_count,
run_id, session_id, user_id, agent_id, team_id, workflow_id,
created_at
```

**`Span`** (`tracing/schemas.py:86`):
```
span_id, trace_id, parent_span_id, name, span_kind,
status_code (OK/ERROR/UNSET), status_message,
start_time, end_time, duration_ms,
attributes: Dict[str, Any],   # all OTel attributes
created_at
```

`Span.from_otel_span(ReadableSpan)` converts from OTel format. Nanosecond timestamps → `datetime` objects. All attribute values normalized to JSON-serializable types.

### 7.5 Span Types and Attributes (`os/routers/traces/schemas.py`)

Span kinds as derived by `_derive_span_type()`:

| Derived Type | OTel `span_kind` | Additional Condition |
|---|---|---|
| `WORKFLOW` | `CHAIN` | any |
| `TEAM` | `AGENT` | has `agno.team.id` attribute |
| `AGENT` | `AGENT` | no `agno.team.id` attribute |
| `LLM` | `LLM` | — |
| `TOOL` | `TOOL` | — |

**LLM span attributes** (via OpenInference):
- `llm.model_name` — model identifier
- `llm.token_count.prompt` — input tokens
- `llm.token_count.completion` — output tokens
- `input.value`, `output.value`

**TOOL span attributes:**
- `tool.name`, `tool.parameters`

**AGENT/TEAM span attributes:**
- `agno.run.id`, `agno.agent.id`, `agno.team.id`
- `session.id`, `user.id`

**WORKFLOW (CHAIN) span attributes:**
- `agno.workflow.id`, `agno.workflow.description`
- `agno.workflow.steps_count`, `agno.workflow.steps`, `agno.workflow.step_types`

### 7.6 Trace Aggregation

`create_trace_from_spans(spans)` builds the `Trace` record from a flat list of spans:
- Finds the root span (no `parent_span_id`)
- Aggregates `start_time = min(...)`, `end_time = max(...)`, `duration_ms`, `error_count`
- Status = ERROR if any span has status ERROR
- If no root span in batch (partial export): context fields are `None` to preserve existing DB values via COALESCE on upsert

### 7.7 `TraceDetail` Hierarchical View

For the UI, `TraceDetail.from_trace_and_spans()` builds a recursive `TraceNode` tree:
- Groups spans by `parent_span_id`
- Aggregates total input/output tokens across all LLM spans
- Attaches `step_type` labels to workflow step nodes

---

## 8. Metrics

**File:** `metrics.py` (top-level module; `models/metrics.py` is a backward-compat shim)

### 8.1 Metrics Hierarchy

```
BaseMetrics                     # base token counters + cost
├── ModelMetrics                # per-model: adds provider, id, provider_metrics
├── MessageMetrics              # per-message: adds timer, duration, ttft
├── RunMetrics                  # per-run: adds timer, duration, ttft, details dict
└── SessionMetrics              # per-session: aggregated across runs
```

`ToolCallMetrics` is a separate, standalone struct (only timing — no tokens).

### 8.2 `BaseMetrics` (`metrics.py:36`)

All metric classes share:
```python
input_tokens: int = 0
output_tokens: int = 0
total_tokens: int = 0
audio_input_tokens: int = 0
audio_output_tokens: int = 0
audio_total_tokens: int = 0
cache_read_tokens: int = 0
cache_write_tokens: int = 0
reasoning_tokens: int = 0
cost: Optional[float] = None
```

### 8.3 `ModelType` Enum (`metrics.py:10`)

Identifies the functional role of each model within a run:

| Key | Usage |
|---|---|
| `MODEL` | Primary agent model |
| `OUTPUT_MODEL` | Structured output parser |
| `PARSER_MODEL` | Response parser |
| `MEMORY_MODEL` | Memory summarization |
| `REASONING_MODEL` | Reasoning / thinking |
| `SESSION_SUMMARY_MODEL` | Session summarization |
| `CULTURE_MODEL` | Culture/eval model |
| `LEARNING_MODEL` | Learning/instruction model |
| `COMPRESSION_MODEL` | Tool result compression |
| `FOLLOWUP_MODEL` | Follow-up question generation |

### 8.4 `RunMetrics` (`metrics.py:279`)

```python
@dataclass
class RunMetrics(BaseMetrics):
    timer: Optional[Timer]
    time_to_first_token: Optional[float]    # seconds to first streaming token
    duration: Optional[float]               # total run duration in seconds
    details: Optional[Dict[str, List[ModelMetrics]]]
    # Keys are ModelType strings; values are lists of ModelMetrics (one per provider+id)
    additional_metrics: Optional[Dict[str, Any]]
```

`RunMetrics + RunMetrics` (`__add__`) aggregates all fields:
- Token counts: summed
- Duration: summed
- TTFT: minimum (earliest)
- Cost: summed
- `details`: merged by `(model_type, provider, id)` key — tokens accumulated per model instance
- `additional_metrics`: numeric values summed, others overwritten

`RunMetrics.from_dict()` properly reconstructs `details` → `List[ModelMetrics]`.

### 8.5 `ModelMetrics` (`metrics.py:56`)

```python
@dataclass
class ModelMetrics(BaseMetrics):
    id: str = ""
    provider: str = ""
    provider_metrics: Optional[Dict[str, Any]] = None  # provider-specific extras
```

`accumulate(other: ModelMetrics)` adds token counts, merges cost and `provider_metrics`.

### 8.6 `ToolCallMetrics` (`metrics.py:115`)

```python
@dataclass
class ToolCallMetrics:
    timer: Optional[Timer]
    start_time: Optional[float]   # epoch float
    end_time: Optional[float]     # epoch float
    duration: Optional[float]     # seconds
```

Only timing — no token tracking for tool calls.

### 8.7 `MessageMetrics` (`metrics.py:173`)

Per-message metrics used internally by model providers. Has `provider_metrics` as a transit field — set by providers, consumed by `accumulate_model_metrics` → `ModelMetrics`.

### 8.8 `SessionMetrics` (`metrics.py:452`)

Aggregates across runs. Same `details` structure as `RunMetrics`.
`accumulate_from_run(run_metrics: RunMetrics)` adds a run's metrics into the session totals.

### 8.9 Key Functions (`metrics.py`)

| Function | Purpose |
|---|---|
| `accumulate_model_metrics(model_response, model, model_type, run_metrics)` | Extract metrics from a `ModelResponse` and accumulate into `RunMetrics.details[model_type]` |
| `accumulate_eval_metrics(eval_metrics, run_metrics, prefix)` | Merge reasoning/eval agent metrics into parent run metrics under prefixed key |
| `merge_background_metrics(run_metrics, background_metrics)` | Merge metrics from parallel background agent runs into the primary run metrics |

### 8.10 Exposure

`RunMetrics` is attached to `RunOutput.metrics` (returned from every `agent.run()`). It can be accessed:
```python
response = agent.run("Hello")
print(response.metrics.input_tokens)
print(response.metrics.duration)
print(response.metrics.details)        # per-model breakdown
print(response.metrics.time_to_first_token)
```

There is no separate `AgentMetrics` class — `RunMetrics` is the canonical run-level metric object. `SessionMetrics` accumulates across runs and is stored in `AgentSession`.

---

## Cross-Subsystem Integration Map

```
Agent.run()
├── execute_pre_hooks()          [hooks/_hooks.py]
│   ├── guardrail hooks (sync, blocking)
│   └── non-guardrail hooks (bg or inline)
├── ReasoningManager.reason()   [reasoning/manager.py]
│   ├── native: provider-specific extraction
│   └── default: CoT agent with ReasoningSteps output
├── model.response()
│   └── CompressionManager.compress()  [compression/manager.py]
│       └── LLM call per tool result
├── tool execution
│   └── @approval → ToolExecution.is_paused  [approval/]
│       └── run paused for HITL resolution
├── RunMetrics accumulation     [metrics.py]
│   ├── accumulate_model_metrics (primary model)
│   ├── accumulate_model_metrics (compression model)
│   └── accumulate_eval_metrics (reasoning model)
├── execute_post_hooks()
│   ├── guardrail hooks (sync, blocking)
│   └── non-guardrail hooks (bg or inline)
└── DatabaseSpanExporter.export()  [tracing/]
    └── Span → Trace stored in DB

SchedulePoller (background daemon)
└── ScheduleExecutor._call_endpoint()
    └── HTTP POST to AgentOS agent/team/workflow run endpoint
```

---

## LBM Applicability Notes

| Feature | LBM Relevance |
|---|---|
| **Hooks pre-hooks** | Use for input guardrails (PII scrubbing, auth checks) without modifying agent logic |
| **Hooks post-hooks** | Use for post-run logging, analytics, cache invalidation, memory refresh triggers |
| **`run_in_background=True`** | Use for non-critical post-hooks (notifications, analytics) to avoid adding latency to the user-facing response |
| **Compression** | Configure `compress_token_limit` when using Gemini 1M context; leave default `compress_tool_results_limit=3` for RAG pipelines with many tool calls |
| **Skills** | Use for domain-expert skill packs (e.g., medical ontology, diet analysis) loaded from `C:/Users/USER/Desktop/LBM Memry/skills/` |
| **Scheduler** | Use for `run_eod_workflow`, daily BSV cron jobs, periodic memory resonance — cron via `ScheduleManager.create(cron="0 2 * * *", ...)` |
| **Reasoning** | For Gemini 2.5+: set `thinking_budget > 0` (never 0); reasoning metrics tracked under `"reasoning_model"` in `RunMetrics.details` |
| **Approval** | Use `@approval(type="required")` on any tool that modifies user health data or sends external notifications |
| **Tracing** | Enable via `setup_tracing(db=agno_db)` in AgentOS startup; all LBM runs traced automatically; query via `/v1/traces` |
| **Metrics** | `response.metrics.details["model"]` gives per-provider breakdown; `details["compression_model"]` tracks compression cost; `reasoning_tokens` tracks thinking tokens |
