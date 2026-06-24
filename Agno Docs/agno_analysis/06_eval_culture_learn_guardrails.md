# Agno 2.6.9 — Evals, Culture, Learn & Guardrails
**Subsystems:** eval/, culture/, learn/, guardrails/

---

## Table of Contents

1. [Evals (`eval/`)](#1-evals-eval)
2. [Culture (`culture/`)](#2-culture-culture)
3. [Learn (`learn/`)](#3-learn-learn)
4. [Guardrails (`guardrails/`)](#4-guardrails-guardrails)
5. [Cross-Subsystem Integration Map](#5-cross-subsystem-integration-map)

---

## 1. Evals (`eval/`)

### 1.1 File Map

| File | Key Symbols |
|------|-------------|
| `eval/__init__.py` | Lazy `__getattr__` exports; `BaseEval` eagerly imported |
| `eval/base.py` | `BaseEval` — abstract pre/post-check interface |
| `eval/accuracy.py` | `AccuracyEval`, `AccuracyEvaluation`, `AccuracyResult`, `AccuracyAgentResponse` |
| `eval/agent_as_judge.py` | `AgentAsJudgeEval`, `AgentAsJudgeEvaluation`, `AgentAsJudgeResult` |
| `eval/performance.py` | `PerformanceEval`, `PerformanceResult` |
| `eval/reliability.py` | `ReliabilityEval`, `ReliabilityResult` |
| `eval/utils.py` | `log_eval_run`, `async_log_eval`, `store_result_in_file` |

### 1.2 The Two Eval Roles

Agno has **two separate eval concepts** that share the name but serve different purposes:

**Role A — Standalone Eval Classes** (in `eval/accuracy.py`, `eval/performance.py`, etc.)
These are dataclass-based runners you call directly to benchmark an agent or a Python function. They have their own `.run()` / `.arun()` methods and produce result objects.

**Role B — `BaseEval` as a Hook** (`eval/base.py`)
An abstract base class whose instances can be placed in an agent's `pre_hooks` or `post_hooks`. This is the inline, per-invocation evaluation path. The hook system normalizes them into `.pre_check` / `.post_check` calls (see `utils/hooks.py:89-98`).

```python
# eval/base.py:8-29
class BaseEval(ABC):
    @abstractmethod
    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None: ...
    @abstractmethod
    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None: ...
    @abstractmethod
    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None: ...
    @abstractmethod
    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None: ...
```

### 1.3 `AccuracyEval` — LLM-Graded Output Quality

**Location:** `eval/accuracy.py`

**Purpose:** Run an agent/team against a known input/expected-output pair across N iterations. A separate LLM judge (an `Agent` configured with `AccuracyAgentResponse` output schema) scores each agent response 1-10.

**Key fields (`@dataclass`):**
- `agent` / `team` — the component under test (exactly one)
- `input: str` — the eval question/prompt
- `expected_output: str` — the ground-truth answer  
- `num_iterations: int` — how many times to run for statistical robustness
- `evaluator_agent: Optional[Agent]` — custom judge (default: OpenAI `gpt-4o`)
- `additional_guidelines: Optional[str]` — extra scoring criteria
- `db: Optional[Union[BaseDb, AsyncBaseDb]]` — persist results

**Scoring schema** (`eval/accuracy.py:24-26`):
```python
class AccuracyAgentResponse(BaseModel):
    accuracy_score: int  # 1-10
    accuracy_reason: str
```

**Run loop** (`eval/accuracy.py:343-491`):
1. For each of `num_iterations`: calls `agent.run(input=eval_input, session_id=f"eval_{eval_id}_{i+1}", stream=False)`
2. Builds `evaluation_input` XML block with `<agent_input>`, `<expected_output>`, `<agent_output>`
3. Calls `evaluate_answer()` — judge agent returns `AccuracyAgentResponse`
4. Appends `AccuracyEvaluation(input, output, expected_output, score, reason)` to `AccuracyResult.results`
5. Logs to DB via `log_eval_run()` with `EvalType.ACCURACY`
6. Optionally logs telemetry via `create_eval_run_telemetry()`

**Result stats** (`eval/accuracy.py:74-83`):
```python
def compute_stats(self):
    # avg_score, mean_score, min_score, max_score, std_dev_score
    # uses statistics.mean / statistics.stdev
```

### 1.4 `AgentAsJudgeEval` — Criteria-Based Binary/Numeric Judge

**Location:** `eval/agent_as_judge.py`

**Purpose:** Evaluate arbitrary input/output text against a natural-language criterion string. No pre-built agent needed — works standalone. Extends `BaseEval` (`eval/agent_as_judge.py` via `AgentAsJudgeEval → BaseEval`).

**Key fields:**
- `criteria: str` — natural language description of what to test
- `scoring_strategy: Literal["binary", "numeric"]` — default `"binary"`
- `threshold: int` — only meaningful for `"numeric"`, range 1-10 (default 7), `__post_init__` validates
- `evaluator_agent: Optional[Agent]` — custom judge
- `model: Optional[Model]` — model for auto-built judge (default: OpenAI `gpt-5-mini`)
- `additional_guidelines` — extra criteria lines
- `on_fail: Optional[Callable]` — callback when evaluation fails
- `cases: Optional[List[Dict[str, str]]]` — batch mode input

**Response schemas** (`eval/agent_as_judge.py`):
```python
class NumericJudgeResponse(BaseModel):
    score: int       # 1-10
    reason: str

class BinaryJudgeResponse(BaseModel):
    passed: bool
    reason: str
```

**Judge agent construction** (`eval/agent_as_judge.py:198-271`):
- Builds instructions with `## Criteria`, `## Scoring (1-10)` or `## Evaluation`, `## Additional Guidelines`
- Creates `Agent(model=..., description="You are an expert evaluator...", instructions=..., output_schema=response_schema)`
- Uses `response_schema = NumericJudgeResponse if scoring_strategy == "numeric" else BinaryJudgeResponse`

**Run modes** (`eval/agent_as_judge.py:467-571`):
- **Single mode**: `run(input=..., output=...)` — one evaluation
- **Batch mode**: `run(cases=[{"input": ..., "output": ...}, ...])` — calls `_run_batch()`

**on_fail callback** (`eval/agent_as_judge.py:322-331`):
- Triggered synchronously after failed evaluation (before returning)
- Async `on_fail` is warned-against in sync `run()`, supported in `arun()`

### 1.5 `PerformanceEval` — Runtime and Memory Profiling

**Location:** `eval/performance.py`

**Purpose:** Wrap any callable `func` and measure execution time and/or memory across `num_iterations` runs.

**Key fields:**
- `func: Callable` — the function to benchmark
- `num_iterations: int` — measurement count (default 1)
- `warmup_runs: Optional[int]` — runs before measurement (discarded)
- `measure_runtime: bool` — enable wall-clock timing
- `measure_memory: bool` — enable tracemalloc peak memory
- `memory_growth_tracking: bool` — compare snapshots between runs (debug)
- `top_n_memory_allocations: int` — for snapshot diff logs

**Run sequence** (`eval/performance.py:481-622`):
1. Optional warm-up iterations (function called, discarded)
2. Runtime measurement loop: `Timer.start()` → `func()` → `Timer.stop()` → appends elapsed
3. Memory measurement loop: `tracemalloc` baseline → `tracemalloc.start()` → `func()` → `get_traced_memory()` → subtract baseline → appends MiB
4. Builds `PerformanceResult(run_times=..., memory_usages=...)`
5. Logs to DB with `EvalType.PERFORMANCE`

**Stats available on `PerformanceResult`:**
`avg_run_time`, `min_run_time`, `max_run_time`, `std_dev_run_time`, `median_run_time`, `p95_run_time`, `avg_memory_usage`, `min_memory_usage`, `max_memory_usage`, `std_dev_memory_usage`, `median_memory_usage`, `p95_memory_usage`

### 1.6 `ReliabilityEval` — Tool Call Verification (No LLM Judge)

**Location:** `eval/reliability.py`

**Purpose:** Given an already-executed `agent_response` or `team_response`, verify which tool calls were made. Pure structural check — no additional LLM call.

**Key fields:**
- `agent_response: Optional[RunOutput]` — the response to evaluate
- `team_response: Optional[TeamRunOutput]` — alternative
- `expected_tool_calls: Optional[List[str]]` — tool names that must appear
- `allow_additional_tool_calls: bool` — if `False`, unexpected tool calls → `failed_tool_calls`
- `expected_tool_call_arguments: Optional[Dict[str, Union[Dict, List[Dict]]]]` — partial argument match specs

**Evaluation logic** (`eval/reliability.py:92-204`):
1. Collects all `message.tool_calls` across all messages (including `team_response.member_responses`)
2. For each actual tool call function name:
   - Not in `expected_tool_calls` and `allow_additional_tool_calls=False` → `failed_tool_calls`
   - Not in `expected_tool_calls` and `allow_additional_tool_calls=True` → `additional_tool_calls`
   - In `expected_tool_calls` → `passed_tool_calls`
3. Missing expected tools → `missing_tool_calls`
4. Argument checks: each spec `{"key": value}` must match at least one actual call for that tool (partial match, JSON-parsed from raw string arguments)
5. Pass condition: `len(failed_tool_calls) == 0 and len(missing_tool_calls) == 0 and len(failed_argument_checks) == 0`

```python
result.assert_passed()  # eval/reliability.py:50-51  — raises AssertionError if not PASSED
```

### 1.7 DB Persistence and Telemetry

**`log_eval_run`** (`eval/utils.py:16-49`):
- Calls `db.create_eval_run(EvalRunRecord(...))` with `eval_type: EvalType`, `eval_data: dict`, `eval_input: dict`, plus `agent_id`, `model_id`, `team_id`, `name`, `evaluated_component_name`
- `EvalType` enum values: `ACCURACY`, `PERFORMANCE`, `RELIABILITY`, `AGENT_AS_JUDGE`

**Telemetry**: Each eval type sends to `agno.api.evals.create_eval_run_telemetry()` unless `telemetry=False`.

**File persistence**: `store_result_in_file()` (`eval/utils.py:105-120`) — `json.dumps(asdict(result))` to a path with `{name}` and `{eval_id}` format slots.

### 1.8 Running Evals Programmatically

```python
# Accuracy
from agno.eval import AccuracyEval
eval = AccuracyEval(
    agent=my_agent,
    input="What is the capital of France?",
    expected_output="Paris",
    num_iterations=3,
)
result = eval.run(print_summary=True, print_results=True)

# Agent-as-Judge (binary, standalone — no agent needed)
from agno.eval import AgentAsJudgeEval
judge = AgentAsJudgeEval(
    criteria="The response must be factually accurate and cite at least one source.",
    scoring_strategy="numeric",
    threshold=7,
)
result = judge.run(input="What is relativity?", output=some_output)

# Reliability (post-run check)
from agno.eval import ReliabilityEval
chk = ReliabilityEval(
    agent_response=response,
    expected_tool_calls=["search_web", "calculator"],
    expected_tool_call_arguments={"calculator": {"a": 5, "b": 3}},
)
result = chk.run()
result.assert_passed()

# As an inline hook on agent
agent = Agent(pre_hooks=[my_guardrail], post_hooks=[AgentAsJudgeEval(...)])
```

---

## 2. Culture (`culture/`)

### 2.1 What Culture Is

Culture is Agno's **shared organizational knowledge layer** — a persistent store of best practices, patterns, guardrails, lessons, and principles that agents discover and can read across sessions and agent instances. It is distinct from user memory (per-user, per-session) and learned knowledge (per-agent vector-store insights). Culture lives in a database via `CultureManager`, scoped by `name` (optional namespace).

### 2.2 File Map

| File | Key Symbols |
|------|-------------|
| `culture/__init__.py` | Exports `CultureManager`, `CulturalKnowledge` |
| `culture/manager.py` | `CultureManager` — full CRUD + LLM extraction engine |

### 2.3 `CultureManager` — Core Class

**Location:** `culture/manager.py:57-516`

**Constructor** (`culture/manager.py:60-82`):
```python
CultureManager(
    model=None,           # Model instance or str — default: OpenAI gpt-4o
    db=None,              # BaseDb or AsyncBaseDb for persistence
    system_message=None,  # Full override for extraction system prompt
    culture_capture_instructions=None,  # What to capture (injected into prompt)
    additional_instructions=None,       # Appended to default system prompt
    add_knowledge=True,
    update_knowledge=True,
    delete_knowledge=False,
    clear_knowledge=True,
    debug_mode=False,
)
```

**No YAML format** — culture is stored structurally as `CulturalKnowledge` objects in the database, not as YAML files. There is no static file format for culture.

### 2.4 `CulturalKnowledge` Schema

`CulturalKnowledge` is a DB schema object (imported from `agno.db.schemas.culture`) with these fields (set by the LLM extraction agent via tools):
- `id` — UUID, auto-assigned if not provided
- `name` — short specific title (required)
- `summary` — one-line purpose or takeaway
- `content` — the reusable insight/rule/guideline (required)
- `categories` — list of tags e.g. `['guardrails', 'rules', 'principles', 'practices', 'patterns', 'behaviors', 'stories']`
- `notes` — contextual notes, rationale, examples
- `metadata` — optional structured info (source, author, version)
- `updated_at` — bumped on each upsert

### 2.5 The System Prompt — What Gets Captured

`CultureManager.get_system_message()` (`culture/manager.py:349-458`) builds the extraction prompt dynamically:

```
You are the Cultural Knowledge Manager, responsible for maintaining, evolving, and safeguarding
the shared cultural knowledge for Agents and Multi-Agent Teams.
...
## Criteria for creating cultural knowledge
<knowledge_to_capture>
Cultural knowledge should capture:
- Best practices and successful approaches discovered in previous interactions
- Common patterns in user behavior, team workflows, or recurring issues
- Processes, design principles, or rules of operation
- Guardrails, decision rationales, or ethical guidelines
- Domain-specific lessons that generalize beyond one case
- Communication styles or collaboration methods that lead to better outcomes
- Any other valuable insight that should persist across agents and time
</knowledge_to_capture>
```

Tools exposed to the extraction LLM:
- `add_knowledge` (if `enable_add_knowledge=True`)
- `update_knowledge` (if `enable_update_knowledge=True`)
- `delete_knowledge` (if `enable_delete_knowledge=True`)
- `clear_knowledge` (if `enable_clear_knowledge=True`)

De-duplication rule: "Search existing_knowledge by name/category before adding new entries. If a similar entry exists, update it instead of creating a duplicate."

### 2.6 How Culture Affects Agent Behavior

**Two modes of culture integration in `agent/agent.py`:**

**Mode 1: Read-only context injection** (`add_culture_to_context=True`)
During system message construction (`agent/_messages.py:328-370`):
1. Calls `agent.culture_manager.get_all_knowledge()` 
2. Appends all cultural knowledge entries to the system prompt inside `<cultural_knowledge>` XML block
3. Prompt preamble: "You have access to shared Cultural Knowledge... Reference it to align with shared norms... Apply it contextually, not mechanically..."
4. If no knowledge available: tells agent to "document useful insights you create — they may become future Cultural Knowledge"

**Mode 2: Agentic culture contribution** (`enable_agentic_culture=True`)
Adds extra instructions at `agent/_messages.py:372-`: tells agent to use `create_or_update_cultural_knowledge` tool "when you discover an insight, pattern, rule, or best practice."

**Post-run extraction**: After every agent run, if `agent.update_cultural_knowledge=True` (`agent/_managers.py:272-290`):
```python
agent.culture_manager.create_cultural_knowledge(
    message=run_messages.user_message,
    messages=...,
    run_metrics=...,
)
```
This sends the conversation to the CultureManager's extraction LLM, which decides what (if anything) to add or update.

### 2.7 Agent Fields for Culture (`agent/agent.py`)

```python
culture_manager: Optional[CultureManager] = None   # line 344
enable_agentic_culture: bool = False                # line 346
add_culture_to_context: Optional[bool] = None       # line 350
update_cultural_knowledge: bool                     # (also on agent)
```

### 2.8 CRUD API

```python
# Read
mgr.get_knowledge(id)                # → Optional[CulturalKnowledge]
mgr.get_all_knowledge(name=None)     # → Optional[List[CulturalKnowledge]]

# Write (direct)
mgr.add_cultural_knowledge(knowledge)    # → str (id)
mgr.clear_all_knowledge()

# LLM-mediated extraction (used by agent post-run)
mgr.create_cultural_knowledge(message=..., messages=...)   # → str (response)

# Task-based (e.g. "remove all security guardrails")
mgr.update_culture_task(task)   # → str

# Async variants: aget_*, acreate_cultural_knowledge, aupdate_culture_task
```

### 2.9 Architecture: Model Call Pattern

`create_or_update_cultural_knowledge()` (`culture/manager.py:460-516`):
1. `deepcopy(self.model)` — avoids state mutation
2. Builds tool list from DB method functions (`add_knowledge`, `update_knowledge`, etc.) via `Function.from_callable(tool, strict=True)`
3. Prepares messages: `[system_message, *conversation_messages]`
4. Calls `model_copy.response(messages=..., tools=_tools)` — direct model call (not an Agent)
5. If `response.tool_calls` were made → `self.knowledge_updated = True`
6. Accumulates model metrics into `RunMetrics` if provided

---

## 3. Learn (`learn/`)

### 3.1 What Learn Does

The `learn/` subpackage is the **unified learning and memory system** for agents. It captures structured knowledge from interactions and stores it in typed stores. It is distinct from the legacy `memory/` subpackage. Learn provides:
- **User Profile** — structured long-term facts about a user (name, preferences, etc.)
- **User Memory** — unstructured per-user observations
- **Session Context** — what happened in this session (summary, goals, progress)
- **Entity Memory** — facts about third-party entities (companies, projects, people, systems)
- **Learned Knowledge** — reusable insights stored in a vector knowledge base
- **Decision Log** — agent decision audit trail (Phase 2)

### 3.2 File Map

| File | Key Symbols |
|------|-------------|
| `learn/__init__.py` | Exports `LearningMachine` + all store/config types |
| `learn/machine.py` | `LearningMachine` — unified facade over all stores |
| `learn/config.py` | `LearningMode` enum + all `*Config` dataclasses |
| `learn/schemas.py` | `UserProfile`, `SessionContext`, `LearnedKnowledge`, `EntityMemory`, `Decision` dataclasses |
| `learn/curate.py` | `Curator` — memory maintenance (prune, deduplicate) |
| `learn/utils.py` | `_parse_json`, `_safe_get`, `_truncate_for_log` |
| `learn/stores/__init__.py` | Exports all store classes |
| `learn/stores/protocol.py` | `LearningStore` — protocol (abstract base) |
| `learn/stores/user_profile.py` | `UserProfileStore` |
| `learn/stores/user_memory.py` | `UserMemoryStore` |
| `learn/stores/session_context.py` | `SessionContextStore` |
| `learn/stores/entity_memory.py` | `EntityMemoryStore` |
| `learn/stores/learned_knowledge.py` | `LearnedKnowledgeStore` |
| `learn/stores/decision_log.py` | `DecisionLogStore` |

### 3.3 `LearningMode` — The Four Modes

**Location:** `learn/config.py:32-44`

```python
class LearningMode(Enum):
    ALWAYS   = "always"   # Automatic LLM extraction after each response
    AGENTIC  = "agentic"  # Agent decides when to save via tools
    PROPOSE  = "propose"  # Agent proposes → human approves → saved
    HITL     = "hitl"     # Reserved (human-in-the-loop, future use)
```

| Mode | Trigger | Human needed | Context injection | Requires history |
|------|---------|--------------|-------------------|-----------------|
| `ALWAYS` | Post-run (automatic) | No | Context only | No |
| `AGENTIC` | Agent calls tool | No | Instructions + tools + context | No |
| `PROPOSE` | Agent proposes in text | Yes (says "yes") | Instructions + tools + context | Yes |
| `HITL` | Future | Yes | - | Yes |

`LearningMachine.requires_history` property (`learn/machine.py:347-361`) returns `True` if any store is in `PROPOSE` or `HITL` mode, so the agent framework knows to keep full chat history.

### 3.4 Configuration Dataclasses

All configs are pure `@dataclass` (not Pydantic, intentionally to avoid runtime overhead — `learn/config.py:7`).

**`UserProfileConfig`** (`learn/config.py:52-104`):
- `db`, `model`, `mode=ALWAYS`, `schema=None` (custom subclass of `UserProfile`)
- `enable_update_profile: bool = True`
- `enable_agent_tools: bool = False`, `agent_can_update_profile: bool = True`
- `instructions`, `additional_instructions`, `system_message`

**`UserMemoryConfig`** (`learn/config.py:107-167`):
- Same base fields + `enable_add_memory=True`, `enable_update_memory=True`, `enable_delete_memory=True`, `enable_clear_memories=False`

**`SessionContextConfig`** (`learn/config.py:170-224`):
- `enable_planning: bool = False` — adds goal/plan/progress tracking on top of summary
- `enable_add/update/delete/clear_context` flags

**`LearnedKnowledgeConfig`** (`learn/config.py:227-286`):
- Requires `knowledge` (vector knowledge base — `agno.knowledge.Knowledge`) — cannot save/search without it
- `mode=AGENTIC` (default — agent decides)
- `namespace: str = "global"` — sharing boundary: `"user"`, `"global"`, or custom
- `enable_agent_tools=True`, `agent_can_save=True`, `agent_can_search=True`

**`EntityMemoryConfig`** (`learn/config.py:289-370`):
- `namespace: str = "global"`
- Fine-grained tool controls: `enable_create_entity`, `enable_update_entity`, `enable_add_fact`, `enable_update_fact`, `enable_delete_fact`, `enable_add_event`, `enable_add_relationship`
- `enable_agent_tools=False` by default

**`DecisionLogConfig`** (`learn/config.py:378-409`):
- `mode=ALWAYS`, `enable_agent_tools=True`

**Phase 2/3 stubs:** `FeedbackConfig` (deferred Phase 2), `SelfImprovementConfig` (deferred Phase 3, uses `HITL` mode).

### 3.5 `LearningStore` Protocol

**Location:** `learn/stores/protocol.py`

Abstract interface all stores implement:
```python
class LearningStore(Protocol):
    def recall(self, **kwargs) -> Optional[Any]: ...
    async def arecall(self, **kwargs) -> Optional[Any]: ...
    def process(self, messages, **kwargs) -> None: ...
    async def aprocess(self, messages, **kwargs) -> None: ...
    def build_context(self, data: Any) -> str: ...
    def get_tools(self, **kwargs) -> List[Callable]: ...
    async def aget_tools(self, **kwargs) -> List[Callable]: ...
    @property
    def was_updated(self) -> bool: ...
    @property
    def learning_type(self) -> str: ...
    @property
    def schema(self) -> Any: ...
```

All six concrete stores extend `LearningStore`: `UserProfileStore`, `UserMemoryStore`, `SessionContextStore`, `EntityMemoryStore`, `LearnedKnowledgeStore`, `DecisionLogStore`.

### 3.6 `LearningMachine` — Unified Facade

**Location:** `learn/machine.py`

**Purpose:** Single entry point that lazily initializes and coordinates all configured stores.

**Constructor accepts:**
```python
LearningMachine(
    db=None,               # Shared DB for profile/memory/session stores
    model=None,            # Shared extraction model
    knowledge=None,        # Shared knowledge base for LearnedKnowledge
    namespace=None,        # Default namespace
    user_profile=None,     # bool | UserProfileConfig | UserProfileStore
    user_memory=None,      # bool | UserMemoryConfig | UserMemoryStore
    session_context=None,  # bool | SessionContextConfig | SessionContextStore
    entity_memory=None,    # bool | EntityMemoryConfig | EntityMemoryStore
    learned_knowledge=None,# bool | LearnedKnowledgeConfig | LearnedKnowledgeStore
    decision_log=None,     # bool | DecisionLogConfig | DecisionLogStore
    custom_stores=None,    # Dict[str, LearningStore]
    debug_mode=False,
)
```

Store resolution (`learn/machine.py:164-196`): each config accepts `bool` (use defaults), `Config` object (use with injected `db`/`model`), or a fully constructed `Store` instance. If `learned_knowledge is None` but `knowledge is not None`, auto-enables `LearnedKnowledgeStore`.

**Main API** (`learn/machine.py:367-689`):

```python
# Before agent response — inject context
context_str = machine.build_context(
    user_id=...,
    session_id=...,
    message=current_message,   # semantic search for LearnedKnowledge
    entity_id=...,
    namespace=...,
)

# Get tools to give to agent (AGENTIC/PROPOSE modes)
tools = machine.get_tools(user_id=..., session_id=..., namespace=...)

# After agent response — extract and save
machine.process(
    messages=conversation_messages,
    user_id=..., session_id=..., namespace=...,
)

# Low-level: raw data from all stores
raw = machine.recall(user_id=..., session_id=..., message=...)
```

**Memory curation** (`learn/machine.py:696+`):
```python
machine.curator.prune(user_id="alice", max_age_days=90)
machine.curator.deduplicate(user_id="alice")
```

### 3.7 `LearnedKnowledgeStore` — Three Context Modes

**Location:** `learn/stores/learned_knowledge.py`

The vector-store-backed knowledge is the most sophisticated store. Its `build_context()` method produces different system prompt snippets based on `LearningMode`:

**`AGENTIC` mode** (`learned_knowledge.py:249-315`):
Injects `<learning_system>` block with four hard rules:
1. "Search before answering knowledge-dependent questions" — call `search_learnings` first
2. "ALWAYS search before saving" — check for duplicates before `save_learning`
3. "ALWAYS save when explicitly asked" — "remember", "save", "note" = directives
4. "ALWAYS save team/org goals, constraints, and policies" — org-level context is shared

**`PROPOSE` mode** (`learned_knowledge.py:317-374`):
Same search rules, but saving requires human approval. Agent must end response with a "**Proposed Learning**" block asking "Save this? (yes/no)". Only calls `save_learning` after explicit "yes".

**`ALWAYS` mode** (`learned_knowledge.py:376-395`):
Passive — just injects `<relevant_learnings>` block with search results. No rules injected (extraction is automatic via `process()`).

### 3.8 Schema Dataclasses

**`UserProfile`** (`learn/schemas.py:59+`) — long-term structured profile. Custom fields via subclass:
```python
@dataclass
class MyProfile(UserProfile):
    company: Optional[str] = field(default=None, metadata={"description": "Company name"})
```
The `field(metadata={"description": ...})` pattern ensures the LLM extraction agent sees the description.

**`LearnedKnowledge`** — `title`, `learning`, `context`, `tags`, `namespace`, `created_at`

**`EntityMemory`** — `entity_id`, `entity_type`, `name`, `description`, `properties` (dict), `facts` (list of strings), `events` (episodic list), `relationships`

**`SessionContext`** — `session_id`, `summary`, optionally `goal`, `plan`, `progress` (when `enable_planning=True`)

All schemas implement `from_dict()` (never raises) and `to_dict()`.

### 3.9 Knowledge vs Memory — The Distinction

| Dimension | `learn/stores/learned_knowledge.py` | `learn/stores/user_memory.py` |
|-----------|--------------------------------------|-------------------------------|
| Storage | Vector knowledge base (semantic search) | Database (structured) |
| Scope | `namespace` (user, global, custom) | Per `user_id` |
| Content | Reusable general insights | User-specific observations |
| Retrieval | Semantic search via `query` | Lookup by `user_id` |
| Default mode | `AGENTIC` | `ALWAYS` |
| Example | "FastAPI prefers async route handlers" | "Alice prefers terse responses" |

---

## 4. Guardrails (`guardrails/`)

### 4.1 File Map

| File | Key Symbols |
|------|-------------|
| `guardrails/__init__.py` | Exports `BaseGuardrail`, `OpenAIModerationGuardrail`, `PIIDetectionGuardrail`, `PromptInjectionGuardrail` |
| `guardrails/base.py` | `BaseGuardrail` — abstract base |
| `guardrails/pii.py` | `PIIDetectionGuardrail` |
| `guardrails/prompt_injection.py` | `PromptInjectionGuardrail` |
| `guardrails/openai.py` | `OpenAIModerationGuardrail` |

### 4.2 `BaseGuardrail` — Abstract Interface

**Location:** `guardrails/base.py:8-19`

```python
class BaseGuardrail(ABC):
    @abstractmethod
    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None: ...

    @abstractmethod
    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None: ...
```

- Takes a `RunInput` or `TeamRunInput` (contains `input_content`, `images`, `videos`, etc.)
- Returns `None` on success
- Raises `InputCheckError` to block the request
- `InputCheckError` carries `additional_data` and a `CheckTrigger` enum value

**Important**: `BaseGuardrail` checks only run on **input** (`pre_hooks`). To check output, you would use `BaseEval.post_check`. Guardrails on `post_hooks` also work (they call `.check(run_input)` — but the signature takes `RunInput`, so post-hook guardrails are unconventional; `normalize_post_hooks` at `utils/hooks.py:127-130` shows guardrails are supported in post position too but still call `.check`).

### 4.3 Built-in Guardrail Types

#### `PIIDetectionGuardrail` (`guardrails/pii.py`)

Regex-based PII detection with **masking or blocking** behavior.

```python
PIIDetectionGuardrail(
    mask_pii=False,              # True = mask in-place; False = raise error
    enable_ssn_check=True,       # \b\d{3}-\d{2}-\d{4}\b
    enable_credit_card_check=True,# \b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b
    enable_email_check=True,     # [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}
    enable_phone_check=True,     # \d{3}[\s.-]?\d{3}[\s.-]?\d{4}
    custom_patterns=None,        # Dict[str, Pattern[str]] — added to defaults
)
```

**Masking behavior** (`pii.py:56-63`): When `mask_pii=True`, replaces detected PII with `*` of equal length, then **mutates `run_input.input_content` in-place** so the agent sees masked text.

**Blocking behavior** (`pii.py:65-70`): Raises `InputCheckError("Potential PII detected in input", check_trigger=CheckTrigger.PII_DETECTED, additional_data={"detected_pii": [...]})`

#### `PromptInjectionGuardrail` (`guardrails/prompt_injection.py`)

Static keyword-based injection detection. No LLM call.

```python
PromptInjectionGuardrail(
    injection_patterns=None  # defaults to 17 built-in patterns
)
```

Built-in patterns (`prompt_injection.py:17-36`): `"ignore previous instructions"`, `"ignore your instructions"`, `"you are now a"`, `"forget everything above"`, `"developer mode"`, `"override safety"`, `"disregard guidelines"`, `"system prompt"`, `"jailbreak"`, `"act as if"`, `"pretend you are"`, `"roleplay as"`, `"simulate being"`, `"bypass restrictions"`, `"ignore safeguards"`, `"admin override"`, `"root access"`, `"forget everything"`

Detection is case-insensitive (`lower()` applied). Raises `InputCheckError("Potential jailbreaking or prompt injection detected.", check_trigger=CheckTrigger.PROMPT_INJECTION)`.

#### `OpenAIModerationGuardrail` (`guardrails/openai.py`)

Uses OpenAI's moderation API (model `omni-moderation-latest`). Supports image+text inputs.

```python
OpenAIModerationGuardrail(
    moderation_model="omni-moderation-latest",
    raise_for_categories=None,  # None = raise on any flagged; or list of specific categories
    api_key=None,               # defaults to OPENAI_API_KEY env var
)
```

Categories: `"sexual"`, `"sexual/minors"`, `"harassment"`, `"harassment/threatening"`, `"hate"`, `"hate/threatening"`, `"illicit"`, `"illicit/violent"`, `"self-harm"`, `"self-harm/intent"`, `"self-harm/instructions"`, `"violence"`, `"violence/graphic"`

**Image support** (`openai.py:69-70`): if `run_input.images` is present, builds multimodal input: `[{"type": "text", "text": content}, *images_to_message(images)]`

On violation, raises `InputCheckError(check_trigger=CheckTrigger.INPUT_NOT_ALLOWED, additional_data={"categories": ..., "category_scores": ...})`

### 4.4 Integration with the Agent Run Loop

**How guardrails attach to agents** (`agent/agent.py:183,185`):
```python
pre_hooks: Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]] = None
post_hooks: Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]] = None
```

**Normalization** (`utils/hooks.py:70-110`):
`normalize_pre_hooks()` converts each `BaseGuardrail` instance into its bound `.check` method (sync) or `.async_check` method (async). This happens once at first run via `team._hooks_normalised` guard.

**Identification** (`utils/hooks.py:57-67`):
```python
def is_guardrail_hook(hook: Callable) -> bool:
    return hasattr(hook, "__self__") and isinstance(hook.__self__, BaseGuardrail)
```
Uses `__self__` introspection on the bound method. A TODO comment notes this should be replaced with a `NormalizedHook(fn, kind)` wrapper.

**Execution semantics** (`agent/_hooks.py:73-95`):
```
Guardrails MUST run synchronously so InputCheckError/OutputCheckError can propagate.
Non-guardrail hooks are buffered and only queued AFTER ALL guardrails pass.
This prevents side-effects (logging, webhooks) from firing on rejected input.
deepcopy runs AFTER the guardrail loop so mutations (e.g. PII masking) propagate.
```

In `_run_hooks_in_background=True` mode:
1. Iterate hooks in order
2. If `is_guardrail_hook(hook)` → call synchronously; let `InputCheckError`/`OutputCheckError` propagate
3. If not guardrail → append to `pending_bg_hooks`
4. After all guardrails pass: `deepcopy(all_args)`, dispatch non-guardrail hooks as background tasks

### 4.5 Blocking vs Non-Blocking

| Behavior | Mechanism |
|----------|-----------|
| **Block** (default) | Raise `InputCheckError` — propagates up through the hooks loop, terminates the run |
| **Mask/Transform** | Mutate `run_input.input_content` in-place and return normally (PII masking mode) |
| **Warn only** | Not natively supported — would require custom hook function (not a `BaseGuardrail` subclass) returning `None` after logging |

The exceptions used:
- `InputCheckError` — for pre-hooks/input violations (`agno.exceptions`)
- `OutputCheckError` — for post-hooks/output violations (`agno.exceptions`)
- Both carry `check_trigger: CheckTrigger` and `additional_data: dict`

`CheckTrigger` values seen: `PII_DETECTED`, `PROMPT_INJECTION`, `INPUT_NOT_ALLOWED`

### 4.6 Custom Guardrail Example

```python
from agno.guardrails.base import BaseGuardrail
from agno.exceptions import InputCheckError, CheckTrigger
from agno.run.agent import RunInput

class TopicGuardrail(BaseGuardrail):
    def __init__(self, banned_topics: list[str]):
        self.banned_topics = banned_topics

    def check(self, run_input: RunInput) -> None:
        content = run_input.input_content_string().lower()
        for topic in self.banned_topics:
            if topic in content:
                raise InputCheckError(
                    f"Topic '{topic}' is not allowed.",
                    check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
                    additional_data={"matched_topic": topic},
                )

    async def async_check(self, run_input: RunInput) -> None:
        self.check(run_input)

# Usage
agent = Agent(
    ...,
    pre_hooks=[
        PIIDetectionGuardrail(mask_pii=True),
        PromptInjectionGuardrail(),
        TopicGuardrail(banned_topics=["competitor_x"]),
    ]
)
```

### 4.7 No Native Output Guardrails

There are **no built-in output guardrail types** in `guardrails/`. The three built-ins all operate on `RunInput`. Post-run output checking uses `BaseEval.post_check` (or custom hook functions). `BaseGuardrail` itself takes `Union[RunInput, TeamRunInput]` in its abstract signature — a `BaseGuardrail` placed in `post_hooks` would still call `.check(run_input)` and would need to ignore the post context.

---

## 5. Cross-Subsystem Integration Map

```
Agent.pre_hooks ──[normalize_pre_hooks()]──► list of .check() bound methods
                                              (guardrails run synchronously,
                                               block on InputCheckError)

Agent.post_hooks ──[normalize_post_hooks()]─► list of .post_check() bound methods
                                               (BaseEval subclasses for output eval)

Agent.culture_manager ──► CultureManager
  ├─ add_culture_to_context=True → CultureManager.get_all_knowledge() →
  │   injected into system prompt as <cultural_knowledge>
  ├─ enable_agentic_culture=True → agent gets create_or_update_cultural_knowledge tool
  └─ update_cultural_knowledge=True → post-run: CultureManager.create_cultural_knowledge()

Agent._run → AccuracyEval.run() → agent.run() (separate call, not inline)
             ReliabilityEval.run() → inspects agent_response.messages for tool_calls
             PerformanceEval.run() → wraps agent.run() in Timer + tracemalloc

LearningMachine (standalone, not yet natively wired to Agent constructor)
  ├─ build_context() → called before run, returns str for system prompt injection
  ├─ get_tools() → called before run, tools added to agent's tool list
  └─ process(messages) → called after run, extracts & saves to stores
```

### 5.1 What Is and Isn't Wired into Agent Natively

| Feature | Native Agent field | Wired automatically |
|---------|-------------------|---------------------|
| `CultureManager` | `Agent.culture_manager` | Yes — in `_messages.py` and `_managers.py` |
| `LearningMachine` | No native field (yet) | No — must be called manually or via custom hooks |
| Guardrails | `Agent.pre_hooks` / `post_hooks` | Yes — normalized at first run |
| `AccuracyEval` | No native field | No — called externally |
| `ReliabilityEval` | No native field | No — called externally |
| `AgentAsJudgeEval` | `Agent.post_hooks` (via `BaseEval`) | Partial — if added as hook |
| `PerformanceEval` | No native field | No — wraps externally |

### 5.2 DB Schema Types

All subsystems can optionally persist to a `BaseDb`/`AsyncBaseDb`:
- Evals → `EvalRunRecord` (`db.create_eval_run()`)
- Culture → `CulturalKnowledge` (`db.get_cultural_knowledge()`, `db.upsert_cultural_knowledge()`)
- Learn → Store-specific tables (user profile, memories, session context, entities, learnings, decisions)
- Guardrails → No DB persistence; violations are fire-and-forget exceptions

---

*Analysis performed 2026-06-04 on Agno 2.6.9 source at `C:/Users/USER/Desktop/LBM Memry/venv/Lib/site-packages/agno/`.*
