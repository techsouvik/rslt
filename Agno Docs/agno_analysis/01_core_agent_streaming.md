# Agno 2.6.9 — Core Agent Loop & Streaming
**Subsystems:** `agent/`, `run/`, `context/`

---

## Table of Contents

1. [Agent Class Construction](#1-agent-class-construction)
2. [Entry Points: run() and arun()](#2-entry-points-run-and-arun)
3. [run_dispatch — Pre-Run Setup](#3-run_dispatch--pre-run-setup)
4. [RunContext and RunOutput — The Two Core Data Structures](#4-runcontext-and-runoutput--the-two-core-data-structures)
5. [The Agent Run Loop — _run() (sync, non-streaming)](#5-the-agent-run-loop--_run-sync-non-streaming)
6. [Streaming Run Loop — _run_stream()](#6-streaming-run-loop--_run_stream)
7. [System Prompt Construction](#7-system-prompt-construction)
8. [Memory Injection into Runs](#8-memory-injection-into-runs)
9. [Message Assembly — get_run_messages()](#9-message-assembly--get_run_messages)
10. [How Tool Calls Are Executed](#10-how-tool-calls-are-executed)
11. [Model Streaming Inner Loop — response_stream()](#11-model-streaming-inner-loop--response_stream)
12. [StreamEvent Taxonomy (RunOutputEvent)](#12-streamevent-taxonomy-runoutputevent)
13. [Loop Termination Conditions](#13-loop-termination-conditions)
14. [Cancellation System](#14-cancellation-system)
15. [context/ Subsystem](#15-context-subsystem)
16. [Background Tasks: Memory, Learning, Culture](#16-background-tasks-memory-learning-culture)
17. [Retry and Error Handling](#17-retry-and-error-handling)
18. [Async Variants](#18-async-variants)
19. [Data Flow Summary Diagram](#19-data-flow-summary-diagram)

---

## 1. Agent Class Construction

**File:** `agent/agent.py:69`

`Agent` is a `@dataclass(init=False)` — all fields have defaults; `__init__` is overridden in `agent/_init.py`.

Key constructor fields:

```python
@dataclass(init=False)
class Agent:
    model: Optional[Model] = None
    fallback_config: Optional[FallbackConfig] = None
    name: Optional[str] = None
    id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    session_state: Optional[Dict[str, Any]] = None
    add_session_state_to_context: bool = False
    enable_agentic_state: bool = False
    retries: int = 0
    delay_between_retries: float = 1.0
    exponential_backoff: bool = False
    tool_call_limit: Optional[int] = None
    # ... ~100+ more fields
```

- `run()` and `arun()` are defined at `agent/agent.py:1336` and `agent/agent.py:1443` respectively.
- Both methods are thin wrappers that delegate to `_run.run_dispatch()` / `_run.arun_dispatch()`.

---

## 2. Entry Points: run() and arun()

**File:** `agent/agent.py:1336–1495`

Both methods are overloaded with typed signatures for `stream=True` / `stream=False`:

```python
def run(self, input, *, stream=None, stream_events=None, ...) -> Union[RunOutput, Iterator[...]]:
    return _run.run_dispatch(self, input=input, stream=stream, ...)

def arun(self, input, *, stream=None, ...) -> Union[RunOutput, AsyncIterator[...]]:
    return _run.arun_dispatch(self, input=input, stream=stream, ...)
```

- `stream=False` (default): returns `RunOutput` directly (blocking).
- `stream=True`: returns an `Iterator[Union[RunOutputEvent, RunOutput]]`.
- `stream_events=True` on top of `stream=True`: enables all intermediate lifecycle events (tool call started/completed, memory updates, reasoning steps, etc.).
- `yield_run_output=True`: also yields the final `RunOutput` object at the end of the stream iterator.

---

## 3. run_dispatch — Pre-Run Setup

**File:** `agent/_run.py:1221–1398`

`run_dispatch` is the factory function that performs all pre-run wiring before delegating to `_run` or `_run_stream`:

### Steps in run_dispatch:

1. **Async DB guard** (`agent/_run.py:1251`): raises `RuntimeError` if agent has async DB but `run()` (sync) is called.
2. **Run ID generation** (`agent/_run.py:1255`): `run_id = run_id or str(uuid4())`
3. **Input validation** (`agent/_run.py:1269`): `validate_input(input, agent.input_schema)` — checks against `input_schema` if set.
4. **Hook normalization** (`agent/_run.py:1272–1277`): normalizes `pre_hooks` and `post_hooks` once per agent (flag `_hooks_normalised`).
5. **Session initialization** (`agent/_run.py:1280`): `initialize_session(agent, session_id, user_id)` — resolves or generates session/user IDs.
6. **Agent initialization** (`agent/_run.py:1283`): `agent.initialize_agent(debug_mode)` — lazy-initializes model, tools, MCP, etc.
7. **Media validation** (`agent/_run.py:1285`): validates images/videos/audio/files, assigns object IDs.
8. **RunInput creation** (`agent/_run.py:1290`): wraps raw input + media into a `RunInput` dataclass.
9. **Pre-read session** (`agent/_run.py:1302`): calls `read_or_create_session()` eagerly so it can be reused on the first attempt (avoids double DB round-trip).
10. **Run option resolution** (`agent/_run.py:1306`): `resolve_run_options(agent, stream, stream_events, ...)` — merges per-call args with agent-level defaults.
11. **RunContext construction** (`agent/_run.py:1323`): creates `RunContext(run_id, session_id, user_id, session_state, dependencies, knowledge_filters, metadata, output_schema)`.
12. **response_format** (`agent/_run.py:1342`): `get_response_format(agent, run_context)` — determines Pydantic response model for structured outputs.
13. **RunOutput creation** (`agent/_run.py:1345`): creates `RunOutput(run_id, session_id, agent_id, user_id, agent_name, metadata, session_state, input=run_input)`.
14. **Metrics timer start** (`agent/_run.py:1360`): `run_response.metrics.start_timer()`.
15. **Dispatch** (`agent/_run.py:1363`): routes to `_run_stream(...)` or `_run(...)`.

---

## 4. RunContext and RunOutput — The Two Core Data Structures

### RunContext
**File:** `run/base.py:16–40`

```python
@dataclass
class RunContext:
    run_id: str
    session_id: str
    user_id: Optional[str] = None
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    dependencies: Optional[Dict[str, Any]] = None
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    metadata: Optional[Dict[str, Any]] = None
    session_state: Optional[Dict[str, Any]] = None
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None
    messages: Optional[List[Message]] = None   # live reference, set in get_run_messages()
    tools: Optional[List[Any]] = None           # runtime-resolved callable results
    knowledge: Optional[Any] = None
    members: Optional[List[Any]] = None
```

- `RunContext` is the **per-run mutable shared state**. It is passed through every phase.
- `session_state` is loaded from DB at the start of each run and written back at the end.
- `messages` is set to `run_messages.messages` by `get_run_messages()` so tool hooks can inspect the live message list. Tool hooks receive a shallow copy (list structure protected, Message objects shared).

### RunOutput
**File:** `run/agent.py:609–660`

```python
@dataclass
class RunOutput:
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    input: Optional[RunInput] = None         # original user input + media
    content: Optional[Any] = None            # final answer (str, Pydantic, or dict)
    content_type: str = "str"
    reasoning_content: Optional[str] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None
    messages: Optional[List[Message]] = None # messages stored in memory (add_to_agent_memory=True)
    metrics: Optional[RunMetrics] = None
    tools: Optional[List[ToolExecution]] = None
    images / videos / audio / files / response_audio  # media attached
    citations: Optional[Citations] = None
    references: Optional[List[MessageReferences]] = None
    followups: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    session_state: Optional[Dict[str, Any]] = None
    events: Optional[List[RunOutputEvent]] = None   # stored if store_events=True
    status: RunStatus = RunStatus.running
    requirements: Optional[list[RunRequirement]] = None  # HITL
    workflow_step_id: Optional[str] = None
```

**`RunStatus` values** (`run/base.py:299`): `PENDING`, `RUNNING`, `COMPLETED`, `PAUSED`, `CANCELLED`, `ERROR`.

---

## 5. The Agent Run Loop — `_run()` (sync, non-streaming)

**File:** `agent/_run.py:324–712`

### Full 16-step sequence (docstring verbatim):

```
1. Read or create session
2. Update metadata and session state
3. Resolve dependencies
4. Execute pre-hooks
5. Determine tools for model
6. Prepare run messages
7. Start memory creation in background thread
8. Reason about the task if reasoning is enabled
9. Generate a response from the Model (includes running function calls)
10. Update the RunOutput with the model response
11. Store media if enabled
12. Convert the response to the structured format if needed
13. Execute post-hooks
14. Wait for background memory creation and cultural knowledge creation
15. Create session summary
16. Cleanup and store the run response and session
```

### Key implementation details:

- **Step 1:** `read_or_create_session()` is called (or `pre_session` reused from `run_dispatch` on attempt 0).
- **Step 2:** `update_metadata()` and `load_session_state()` populate `run_context.session_state` from DB. `_initialize_session_state()` injects `user_id`, `session_id`, `run_id` into the state dict.
- **Step 3:** `resolve_run_dependencies()` resolves callable factories in `run_context.dependencies`.
- **Step 4:** `execute_pre_hooks()` — generator is consumed fully via `deque(pre_hook_iterator, maxlen=0)` (no yielding in non-streaming mode).
- **Step 5:** `agent.get_tools()` → `determine_tools_for_model()` — processes all tool types (Function, Toolkit, MCP, ContextProvider) into model-compatible format.
- **Step 6:** `get_run_messages()` — builds the full message list (system + history + user message). See §9.
- **Background:** Three futures launched concurrently via thread pool:
  - `_managers.start_memory_future()` — memory extraction from conversation.
  - `_managers.start_learning_future()` — learning extraction.
  - `_managers.start_cultural_knowledge_future()` — cultural knowledge creation.
- **Step 8:** `handle_reasoning()` — runs optional reasoning pass before main model call.
- **Step 9:** `call_model_with_fallback(agent.model, agent.fallback_config, messages=..., tools=..., ...)` — calls `model.response()` with fallback logic.
- **Step 10:** `update_run_response()` — copies model response content, tool executions, metrics, reasoning into `RunOutput`.
- **HITL check** (`agent/_run.py:544`): if any tool is paused (requires confirmation, user input, external execution), call `handle_agent_run_paused()` which sets `RunStatus.paused` and returns early.
- **Step 12:** `convert_response_to_structured_format()` — parse response into Pydantic model if `output_schema` is set.
- **Step 13:** `execute_post_hooks()` — consumed via `deque()`.
- **Step 14:** `wait_for_open_threads()` — joins all three background futures.
- **Step 15:** session summary creation (if `enable_session_summaries=True`).
- **Step 16:** `cleanup_and_store()` — scrubs sensitive data, saves to DB, updates session.
- **Return:** `run_response` with `status = RunStatus.completed`.

### Retry loop:
- `num_attempts = agent.retries + 1`
- On exception: `time.sleep(delay)` then retry. Delay doubles if `exponential_backoff=True`.
- `RunCancelledException`, `InputCheckError`, `OutputCheckError`, `KeyboardInterrupt` exit without retry.

---

## 6. Streaming Run Loop — `_run_stream()`

**File:** `agent/_run.py:715–1218`

**Signature:** `_run_stream(..., stream_events: bool = False, yield_run_output: Optional[bool] = None) -> Iterator[Union[RunOutputEvent, RunOutput]]`

The streaming loop has the same 13 high-level steps as `_run()`, but:
- Each step *yields* events instead of blocking.
- `stream_events=False` (default): only `RunContentEvent` chunks are yielded (plain streaming text).
- `stream_events=True`: full lifecycle events are yielded at each stage.

### Key streaming-specific behavior:

**At start of each attempt:**
```python
if stream_events:
    yield handle_event(create_run_started_event(run_response), ...)
```

**Model response processing** (`agent/_run.py:911–961`):
```python
for event in handle_model_response_stream(agent, ...):
    raise_if_cancelled(run_response.run_id)
    yield event
```
Each `event` is either a `RunContentEvent` (text chunk), `ToolCallStartedEvent`, `ToolCallCompletedEvent`, `ModelRequestStartedEvent`, etc.

**If output_model set:** intermediate content is wrapped in `IntermediateRunContentEvent` and the structured output runs through `generate_response_with_output_model_stream()`.

**HITL pause** (`agent/_run.py:983`):
```python
if any(tool_call.is_paused for tool_call in run_response.tools or []):
    yield from handle_agent_run_paused_stream(...)
    return
```

**At end of successful run:**
```python
if stream_events:
    yield handle_event(create_run_content_completed_event(...), ...)
# ... post-hooks, memory wait, session summary ...
if stream_events:
    yield completed_event  # RunCompletedEvent
if yield_run_output:
    yield run_response     # the full RunOutput object
```

**Finally block** (`agent/_run.py:1205`):
- Cancels unfulfilled background futures.
- `disconnect_connectable_tools(agent)` — closes MCP/connectable tool connections.
- `cleanup_run(run_response.run_id)` — removes from cancellation tracker.

---

## 7. System Prompt Construction

**File:** `agent/_messages.py:106–450`

`get_system_message(agent, session, run_context, tools, add_session_state_to_context)` assembles the system prompt from up to 17 named sections:

| Step | Field/Feature | Condition |
|------|--------------|-----------|
| 1 | `agent.system_message` (str, callable, or `Message`) | If set, use directly (no further building) |
| 2 | `agent.build_context = False` | Return `None` |
| 3.1 | `agent.instructions` (str, list, or callable) | Always |
| 3.1.1 | `agent.model.get_instructions_for_model(tools)` | Model-specific instructions |
| 3.2.1 | `"Use markdown to format your answers."` | `agent.markdown=True` |
| 3.2.2 | Current datetime | `agent.add_datetime_to_context=True` |
| 3.2.3 | Current location (IP-based) | `agent.add_location_to_context=True` |
| 3.2.4 | Agent name | `agent.add_name_to_context=True` |
| 3.3.1 | `agent.description` | If set |
| 3.3.2 | `<your_role>` block from `agent.role` | If set |
| 3.3.3 | `<instructions>` block | If instructions exist |
| 3.3.4 | `<additional_information>` block | If additional_information list non-empty |
| 3.3.5 | Tool instructions (`agent._tool_instructions`) | If tools have instructions |
| 3.3.7 | `<expected_output>` | `agent.expected_output` |
| 3.3.8 | `agent.additional_context` | If set |
| 3.3.8.1 | Skills snippet | `agent.skills` |
| **3.3.9** | **`<memories_from_previous_interactions>`** | `agent.add_memories_to_context=True` |
| **3.3.10** | **`<cultural_knowledge>`** | `agent.add_culture_to_context=True` |
| 3.3.11 | `<summary_of_previous_interactions>` | `agent.add_session_summary_to_context=True` |
| 3.3.12 | Learnings block | `agent.add_learnings_to_context=True` |
| 3.3.13 | `search_knowledge` instructions | `agent.search_knowledge and agent.add_search_knowledge_instructions` |
| 3.3.14 | Model-specific system message suffix | `agent.model.get_system_message_for_model(tools)` |
| 3.3.15 | JSON output prompt | `output_schema` set, no native structured outputs, no parser model |
| 3.3.16 | Response model format prompt | `output_schema + parser_model` |
| 3.3.17 | `<session_state>` block | `add_session_state_to_context=True` |

**State variable substitution** (`agent/_messages.py:56–98`): `format_message_with_state_variables()` uses Python's `string.Template.safe_substitute()` to replace `{var_name}` patterns in the system prompt with values from `session_state`, `dependencies`, `metadata`, `user_id`.

The final `Message(role=agent.system_message_role, content=system_message_content.strip())` is returned (role defaults to `"system"`).

---

## 8. Memory Injection into Runs

**File:** `agent/_messages.py:287–325` (within `get_system_message`)

Memory injection happens **during system prompt construction** at step 3.3.9:

```python
if agent.add_memories_to_context:
    user_memories = agent.memory_manager.get_user_memories(user_id=user_id)
    if user_memories and len(user_memories) > 0:
        system_message_content += "You have access to user info..."
        system_message_content += "<memories_from_previous_interactions>"
        for _memory in user_memories:
            system_message_content += f"\n- {_memory.memory}"
        system_message_content += "\n</memories_from_previous_interactions>\n\n"
```

- If `user_id` is None, it defaults to `"default"` (line 290).
- If `memory_manager` is not set, it is lazily initialized via `set_memory_manager(agent)` and then cleared after injection (to avoid leaking state across runs when not explicitly configured).
- If `enable_agentic_memory=True`, an `<updating_user_memories>` block is added that instructs the agent to call the `update_user_memory` tool during the conversation.

**Memory is ALSO created concurrently** in the background (step 7 of the run loop) via `_managers.start_memory_future()`. This future runs memory extraction from `run_messages` while the main model call proceeds, and is joined at step 14 before the run completes.

---

## 9. Message Assembly — `get_run_messages()`

**File:** `agent/_messages.py:1156–1358`

Builds a `RunMessages` object with the full message list:

```
RunMessages:
    system_message: Optional[Message]
    user_message: Optional[Message]
    extra_messages: Optional[List[Message]]
    messages: List[Message]   ← the full list sent to the model
```

Assembly order:
1. **System message** (`get_system_message()`) → `messages[0]`
2. **Extra messages** (`agent.additional_input`) → appended to messages
3. **History** (`session.get_messages(last_n_runs=..., limit=..., skip_roles=[...])`) → appended, tagged `from_history=True`
   - Capped by `agent.num_history_runs` and `agent.num_history_messages`.
   - Tool calls filtered by `agent.max_tool_calls_from_history`.
4. **User message** (`get_user_message()`) — built from input + media + knowledge retrieval. Handles:
   - `str` → user message with content
   - `BaseModel` → JSON-serialized to user message
   - `Message` → used directly
   - `dict` with role → validated as `Message`
   - `List[Message]` → appended as extra messages
5. `run_context.messages = run_messages.messages` is set here (for tool hook access).

**Knowledge injection** happens inside `get_user_message()` — relevant docs are retrieved from the knowledge base and appended to the user message content.

---

## 10. How Tool Calls Are Executed

The tool execution chain spans three layers:

### Layer 1: Model requests tool calls (models/base.py)

Inside `response_stream()` (`models/base.py:1499–1578`) or `response()`, after each model response:

```python
if assistant_message.tool_calls is not None:
    function_calls_to_run = self.get_function_calls_to_run(assistant_message, messages, functions)
    for function_call_response in self.run_function_calls(
        function_calls=function_calls_to_run,
        function_call_results=function_call_results,
        current_function_call_count=function_call_count,
        function_call_limit=tool_call_limit,
    ):
        yield function_call_response
```

### Layer 2: run_function_calls / run_function_call (models/base.py:2299 / 2125)

`run_function_calls()` iterates over each `FunctionCall`. For each:

1. **HITL checks** (`models/base.py:2322`): if `requires_confirmation`, `requires_user_input`, or `external_execution` → creates a paused `ToolExecution`, adds to `run_response.requirements`, skips execution.
2. **Yields `ToolCallStartedEvent`** (as a `ModelResponse` with `event=tool_call_started`).
3. **Calls `function_call.execute()`** (the actual tool execution).
4. **Handles generator results**: if the tool returns a generator/iterator (e.g., a sub-agent's `run(stream=True)`), iterates and yields each event up the stack.
5. **Yields `ToolCallCompletedEvent`** with result, timing, media artifacts.

**Tool call limit**: if `function_call_count > tool_call_limit`, creates an error result and skips execution.

### Layer 3: FunctionCall.execute() (tools/function.py:1019)

```python
def execute(self) -> FunctionExecutionResult:
    self._handle_pre_hook()
    entrypoint_args = self._build_entrypoint_args()
    # Cache check (if function.cache_results=True)
    if self.function.tool_hooks:
        chain = self._build_nested_execution_chain(entrypoint_args)
        result = chain(self.function.name, self.function.entrypoint, self.arguments or {})
    else:
        result = self.function.entrypoint(**entrypoint_args, **self.arguments)
    # Handle generator result
    # Post-hook
    self._handle_post_hook()
    return FunctionExecutionResult(status="success"/"failure", result=result, ...)
```

**Argument injection**: `_build_entrypoint_args()` inspects the function signature by name AND by type hint to inject `agent`, `team`, `run_context`, `fc`, `images`, `videos`, `audios`, `files` as needed.

**Session state propagation**: if the tool receives `run_context` and mutates `run_context.session_state`, those changes are captured in `FunctionExecutionResult.updated_session_state` and merged back into the model's message list via `format_function_call_results()`.

### Loop continuation / termination:
After processing all tool call results (`models/base.py:1554–1578`):
- `stop_after_tool_call=True` on any result → `break`
- Any `requires_confirmation`, `external_execution`, `requires_user_input` → `break`
- Unresolved `run_response.requirements` → `break`
- Otherwise → `continue` (loop back, call model again with tool results in messages)

---

## 11. Model Streaming Inner Loop — `response_stream()`

**File:** `models/base.py:1359–1598`

This is the **inner agentic loop** — the `while True:` that handles multi-turn tool use within a single agent run:

```
while True:
    [optional compression step]
    yield ModelResponse(event=model_request_started)
    for chunk in process_response_stream(messages, assistant_message, stream_data, ...):
        yield chunk   ← these become RunContentEvent chunks upstream
    messages.append(assistant_message)
    yield ModelResponse(event=model_request_completed, input_tokens=..., ...)
    
    if assistant_message.tool_calls:
        for fc_event in run_function_calls(...):
            yield fc_event  ← ToolCallStarted/Completed events
        # add results to messages
        if stop_condition: break
        continue  ← next model call
    
    break  ← no tool calls, done
```

**`process_response_stream()`** calls `_invoke_stream_with_retry()` which calls the actual provider SDK (OpenAI, Gemini, Anthropic, etc.) and yields raw `ModelResponse` delta objects. `_populate_stream_data()` accumulates content, tool call chunks, and reasoning into `stream_data` and `assistant_message`.

**Cache layer** (`models/base.py:1376`): if `model.cache_response=True`, checks for a cache hit before calling the provider. On cache miss, collects all streaming responses and saves to cache after stream ends.

**Compression** (`models/base.py:1408`): if `compression_manager` is set and `should_compress()` is True, compresses existing tool results in the messages list before the next model call. Emits `CompressionStartedEvent` / `CompressionCompletedEvent`.

---

## 12. StreamEvent Taxonomy (RunOutputEvent)

**File:** `run/agent.py:143–558`

`RunOutputEvent` is a `Union` of 37 dataclass types. All inherit from `BaseAgentRunEvent → BaseRunOutputEvent`.

### Complete event list:

| Event Class | Event String | When Yielded |
|-------------|-------------|--------------|
| `RunStartedEvent` | `RunStarted` | Start of `_run_stream`, when `stream_events=True` |
| `RunContentEvent` | `RunContent` | Each text chunk from model (always yielded when `stream=True`) |
| `IntermediateRunContentEvent` | `RunIntermediateContent` | Model text when `output_model` is set (pre-structured output) |
| `RunContentCompletedEvent` | `RunContentCompleted` | After last content chunk, before post-hooks |
| `RunCompletedEvent` | `RunCompleted` | Final event; carries full content, metrics, session_state |
| `RunErrorEvent` | `RunError` | On exception in stream |
| `RunCancelledEvent` | `RunCancelled` | On `RunCancelledException` or `KeyboardInterrupt` |
| `RunPausedEvent` | `RunPaused` | When HITL tools pause the run |
| `RunContinuedEvent` | `RunContinued` | When a paused run is resumed |
| `PreHookStartedEvent` | `PreHookStarted` | Before each pre-hook |
| `PreHookCompletedEvent` | `PreHookCompleted` | After each pre-hook |
| `PostHookStartedEvent` | `PostHookStarted` | Before each post-hook |
| `PostHookCompletedEvent` | `PostHookCompleted` | After each post-hook |
| `ToolCallStartedEvent` | `ToolCallStarted` | Before each tool execution |
| `ToolCallCompletedEvent` | `ToolCallCompleted` | After each tool execution (with result, timing, media) |
| `ToolCallErrorEvent` | `ToolCallError` | On tool execution error |
| `ReasoningStartedEvent` | `ReasoningStarted` | Before reasoning pass |
| `ReasoningStepEvent` | `ReasoningStep` | Each reasoning step |
| `ReasoningContentDeltaEvent` | `ReasoningContentDelta` | Streaming reasoning chunk |
| `ReasoningCompletedEvent` | `ReasoningCompleted` | After reasoning pass |
| `MemoryUpdateStartedEvent` | `MemoryUpdateStarted` | When background memory future starts |
| `MemoryUpdateCompletedEvent` | `MemoryUpdateCompleted` | When background memory future completes |
| `SessionSummaryStartedEvent` | `SessionSummaryStarted` | Before session summary creation |
| `SessionSummaryCompletedEvent` | `SessionSummaryCompleted` | After session summary creation |
| `ParserModelResponseStartedEvent` | `ParserModelResponseStarted` | Before parser model call |
| `ParserModelResponseCompletedEvent` | `ParserModelResponseCompleted` | After parser model call |
| `OutputModelResponseStartedEvent` | `OutputModelResponseStarted` | Before output model call |
| `OutputModelResponseCompletedEvent` | `OutputModelResponseCompleted` | After output model call |
| `ModelRequestStartedEvent` | `ModelRequestStarted` | Before each LLM API call |
| `ModelRequestCompletedEvent` | `ModelRequestCompleted` | After each LLM API call (with token counts, TTFT) |
| `CompressionStartedEvent` | `CompressionStarted` | Before tool result compression |
| `CompressionCompletedEvent` | `CompressionCompleted` | After compression (with size stats) |
| `FollowupsStartedEvent` | `FollowupsStarted` | Before followup suggestion generation |
| `FollowupsCompletedEvent` | `FollowupsCompleted` | After followup generation |
| `CustomEvent` | `CustomEvent` | User-defined events from tools |

**`BaseAgentRunEvent` common fields** (`run/agent.py:197`):
```python
created_at: int      # Unix timestamp
event: str           # event string identifier
agent_id: str
agent_name: str
run_id: Optional[str]
parent_run_id: Optional[str]
session_id: Optional[str]
workflow_id / workflow_run_id / step_id / step_name / step_index  # workflow context
nested_depth: int    # nesting level (0 = top-level)
tools: Optional[List[ToolExecution]]
content: Optional[Any]  # backwards compat
```

**`handle_event()`** (`utils/events.py`): wraps event creation, optionally stores to `run_response.events` if `store_events=True`, and filters events in `agent.events_to_skip`.

### SSE format:
Events are transmitted via `BaseRunOutputEvent.to_json()` which calls `to_dict()` then `json.dumps()`. All `None` fields are excluded. The `to_dict()` method handles special serialization for `ToolExecution`, `RunMetrics`, media objects, and `BaseModel` content fields.

---

## 13. Loop Termination Conditions

The agentic loop in `response_stream()` (`models/base.py:1407–1581`) terminates when ANY of:

| Condition | Location | Effect |
|-----------|----------|--------|
| No `tool_calls` in response | `models/base.py:1580` | `break` — normal completion |
| `stop_after_tool_call=True` on any result | `models/base.py:1555` | `break` — tool requested stop |
| Any tool has `requires_confirmation=True` | `models/base.py:1559` | `break` → HITL pause |
| Any tool has `external_execution=True` | `models/base.py:1563` | `break` → external execution pause |
| Any tool has `requires_user_input=True` | `models/base.py:1567` | `break` → user input pause |
| `run_response.requirements` has unresolved items | `models/base.py:1573` | `break` → propagated HITL from member agent |
| `tool_call_limit` exceeded | `models/base.py:2315` | Error result added, loop continues |
| `RunCancelledException` raised | `agent/_run.py:1111` | Loop exits, `RunCancelledEvent` yielded |

**After the inner model loop, at the run loop level** (`agent/_run.py:983`):
```python
if any(tool_call.is_paused for tool_call in run_response.tools or []):
    yield from handle_agent_run_paused_stream(...)
    return   # terminates the generator
```

---

## 14. Cancellation System

**File:** `run/cancel.py`, `run/cancellation_management/`

### Architecture:
- Global singleton: `_cancellation_manager: BaseRunCancellationManager = InMemoryRunCancellationManager()` (`run/cancel.py:10`)
- Swappable via `set_cancellation_manager()` (e.g., for Redis-backed distributed cancellation).
- All runs tracked by `run_id` in a dict.

### Lifecycle:
1. `register_run(run_id)` — called at the start of `_run()` / `_run_stream()`.
2. `raise_if_cancelled(run_id)` — polled at 5 points in the run loop (before/after memory start, before model call, after model call, after tool processing).
3. `cancel_run(run_id)` — external API to cancel a running agent.
4. `cleanup_run(run_id)` — called in `finally` block, always, whether success or failure.

### `InMemoryRunCancellationManager`:
- Stores `{run_id: is_cancelled}` in a Python dict.
- `raise_if_cancelled()` raises `RunCancelledException` if the flag is set.

### `RedisRunCancellationManager`:
- Uses Redis keys for distributed cancellation across processes.

---

## 15. context/ Subsystem

**File:** `context/provider.py`, `context/backend.py`

The `context/` subsystem is NOT the `RunContext` data object. It is a separate subsystem for **external data sources** (files, web, databases, Slack, Gmail, Google Drive, MCP servers, etc.) that can be injected into an agent's context.

### ContextProvider (abstract base)
**File:** `context/provider.py:75`

```python
class ContextProvider(ABC):
    def __init__(self, id, *, name, mode: ContextMode, model, read, write, ...):
        self.query_tool_name = f"query_{id}"
        self.update_tool_name = f"update_{id}"

    @abstractmethod
    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer: ...
    @abstractmethod
    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer: ...
```

### ContextMode (context/mode.py):
- `default` — each subclass decides how to expose itself
- `agent` — wraps behind a sub-agent; caller gets a single `query_<id>` tool
- `tools` — exposes underlying tools directly to the calling agent

### ContextBackend (context/backend.py):
The backend is the I/O layer (actual network/filesystem calls). The provider owns the agent-facing contract; the backend owns the connection. Backends implement:
- `status()` / `astatus()` → `Status(ok, detail)`
- `get_tools()` → list of tools
- `asetup()` / `aclose()` — resource lifecycle

### Available providers:
`calendar`, `database`, `fs` (filesystem), `gdrive`, `gmail`, `google`, `mcp`, `slack`, `web` (Exa, parallel), `wiki` (Notion, Git), `workspace`.

### How context providers flow into a run:
Context providers are typically added as `Toolkit` objects or as entries in `agent.tools`. When `determine_tools_for_model()` processes them, each provider's tools are resolved and passed to the model's `_format_tools()` call. The `run_context` is injected into each tool call's `entrypoint_args` if the tool signature accepts it.

---

## 16. Background Tasks: Memory, Learning, Culture

**File:** `agent/_managers.py`

Three background futures are launched concurrently with the main model call in both `_run()` and `_run_stream()`:

### 1. Memory Future
```python
memory_future = _managers.start_memory_future(agent, run_messages, user_id, existing_future)
```
- Extracts user memories from the current conversation.
- Uses `agent.memory_manager` (a `MemoryManager` from `memory/manager.py`).
- In async mode: `astart_memory_task()` creates an asyncio Task.

### 2. Learning Future
```python
learning_future = _managers.start_learning_future(agent, run_messages, session, user_id, existing_future)
```
- Extracts learnings from the conversation (LearningMachine: `agent._learning`).
- Runs concurrently in a thread pool.

### 3. Cultural Knowledge Future
```python
cultural_knowledge_future = _managers.start_cultural_knowledge_future(agent, run_messages, existing_future)
```
- Creates or updates cultural knowledge entries (CultureManager: `agent.culture_manager`).
- Runs concurrently in a thread pool.

### Waiting and metric merging:
At the end of the run, `wait_for_open_threads()` (sync) or `await_for_open_threads()` (async) joins all three futures. Background metrics (token usage from memory/learning LLM calls) are merged back into `run_response.metrics` via `merge_background_metrics()`.

In streaming mode, `wait_for_thread_tasks_stream()` yields `MemoryUpdateStartedEvent` / `MemoryUpdateCompletedEvent` events while waiting, if `stream_events=True`.

### On error:
The `finally` block cancels all futures that haven't completed. This prevents leaked background threads.

---

## 17. Retry and Error Handling

**File:** `agent/_run.py:383–696`

The retry loop wraps the entire per-attempt execution:

```python
num_attempts = agent.retries + 1
for attempt in range(num_attempts):
    try:
        # ... full run ...
    except RunCancelledException:   # no retry
        ...
    except (InputCheckError, OutputCheckError):  # no retry (guardrail failure)
        ...
    except KeyboardInterrupt:  # no retry
        ...
    except Exception:
        if attempt < num_attempts - 1:
            delay = agent.delay_between_retries * (2**attempt if agent.exponential_backoff else 1)
            time.sleep(delay)
            continue
        # Final attempt failed
        run_response.status = RunStatus.error
```

**Guardrail errors** (`InputCheckError`, `OutputCheckError`):
- `check_trigger` tells which guardrail fired.
- `error_id` and `additional_data` available for structured error reporting.
- In streaming: `create_run_error_event()` is yielded before exiting.

**Fallback models** (`models/fallback.py:131`):
- `call_model_with_fallback()` catches `ModelProviderError` and tries fallback models in order.
- Fallback routing: `on_rate_limit` (429) → `on_context_overflow` (context window) → `on_error` (other 5xx/network).
- Non-retryable 4xx errors (401, 403, 400 etc.) bypass `on_error` entirely.

---

## 18. Async Variants

The framework provides full async mirrors for every synchronous function:

| Sync | Async |
|------|-------|
| `run_dispatch` | `arun_dispatch` |
| `_run` | `_arun` |
| `_run_stream` | `_arun_stream` |
| `get_run_messages` | `aget_run_messages` |
| `get_system_message` | `aget_system_message` |
| `get_user_message` | `aget_user_message` |
| `execute_pre_hooks` | `aexecute_pre_hooks` |
| `execute_post_hooks` | `aexecute_post_hooks` |
| `read_or_create_session` | `aread_or_create_session` |
| `handle_model_response_stream` | `ahandle_model_response_stream` |
| `call_model_with_fallback` | `acall_model_with_fallback` |
| `call_model_stream_with_fallback` | `acall_model_stream_with_fallback` |

**`_arun()`** (`agent/_run.py:1401`): uses `asyncio.Task` instead of `ThreadPoolExecutor` futures for background work. MCP tool disconnection uses `await disconnect_mcp_tools()`.

**`_arun_stream()`** (`agent/_run.py:2046`): returns `AsyncIterator[RunOutputEvent]`. Uses `async for event in ahandle_model_response_stream(...)`.

**Key difference**: `arun_dispatch` does NOT guard against async DB — it is the expected path for async DBs.

---

## 19. Data Flow Summary Diagram

```
Agent.run(input, stream=True, stream_events=True)
  │
  └─► _run.run_dispatch()
        ├── validate_input()
        ├── initialize_session()
        ├── agent.initialize_agent()
        ├── read_or_create_session()   [pre-read for attempt 0]
        ├── resolve_run_options()
        ├── RunContext(run_id, session_id, user_id, session_state, ...)
        ├── RunOutput(run_id, agent_id, ..., input=RunInput)
        └── _run_stream(agent, run_response, run_context, ...)
              │
              ├── register_run(run_id)          [cancellation tracking]
              ├── read_or_create_session()      [attempt 0: reuse pre-read]
              ├── load_session_state() → run_context.session_state
              ├── resolve_run_dependencies()
              ├── execute_pre_hooks()           [yield pre-hook events]
              ├── get_tools() + determine_tools_for_model()
              ├── get_run_messages()
              │     ├── get_system_message()   ← memories, culture, summary, learnings injected here
              │     ├── history from session.get_messages()
              │     └── get_user_message()     ← knowledge retrieval injected here
              ├── start_memory_future()         [background thread]
              ├── start_learning_future()       [background thread]
              ├── start_cultural_knowledge_future() [background thread]
              │
              ├── yield RunStartedEvent
              ├── handle_reasoning_stream()     [optional]
              │
              └── handle_model_response_stream()
                    └── call_model_stream_with_fallback()
                          └── model.response_stream()
                                ├── while True:  [INNER AGENTIC LOOP]
                                │     ├── [compress?] → yield CompressionStarted/Completed
                                │     ├── yield ModelRequestStarted
                                │     ├── process_response_stream()
                                │     │     └── invoke_stream_with_retry() → provider SDK
                                │     │           └── yield RunContentEvent chunks ◄── TEXT TOKENS
                                │     ├── messages.append(assistant_message)
                                │     ├── yield ModelRequestCompleted (token counts)
                                │     │
                                │     └── if tool_calls:
                                │           ├── yield ToolCallStartedEvent
                                │           ├── FunctionCall.execute()  [actual tool Python fn]
                                │           ├── yield tool results / sub-agent events
                                │           ├── yield ToolCallCompletedEvent
                                │           ├── format_function_call_results() → add to messages
                                │           └── [stop condition?] break or continue
                                │
              ├── yield RunContentCompletedEvent
              ├── execute_post_hooks()          [yield post-hook events]
              ├── wait_for_thread_tasks_stream()
              │     └── yield MemoryUpdateStarted/Completed
              ├── create_session_summary()
              ├── yield SessionSummaryStarted/Completed
              ├── run_response.status = COMPLETED
              ├── cleanup_and_store()           [DB write]
              ├── yield RunCompletedEvent       [final event with full content + metrics]
              └── yield run_response            [if yield_run_output=True]
```

---

## Key File Index

| File | Purpose |
|------|---------|
| `agent/agent.py` | `Agent` class definition; `run()`, `arun()` entry points |
| `agent/_run.py` | `run_dispatch`, `_run`, `_run_stream`, `_arun`, `_arun_stream` |
| `agent/_messages.py` | `get_run_messages`, `get_system_message`, `get_user_message` |
| `agent/_response.py` | `handle_model_response_stream`, `update_run_response`, `generate_response_with_output_model_stream` |
| `agent/_managers.py` | Background memory/learning/culture futures |
| `agent/_hooks.py` | `execute_pre_hooks`, `execute_post_hooks` |
| `agent/_tools.py` | `determine_tools_for_model` |
| `agent/_storage.py` | `read_or_create_session`, `load_session_state`, `cleanup_and_store` |
| `run/agent.py` | `RunInput`, `RunOutput`, `RunEvent`, all event dataclasses, `RunOutputEvent` union |
| `run/base.py` | `RunContext`, `BaseRunOutputEvent`, `RunStatus` |
| `run/cancel.py` | Cancellation manager facade (register/cancel/raise/cleanup) |
| `run/messages.py` | `RunMessages` dataclass |
| `models/base.py` | `response()`, `response_stream()`, `run_function_calls()`, `run_function_call()` |
| `models/fallback.py` | `call_model_with_fallback`, `call_model_stream_with_fallback` |
| `tools/function.py` | `Function`, `FunctionCall`, `FunctionCall.execute()`, `@tool` decorator |
| `tools/decorator.py` | `@tool` decorator implementation |
| `context/provider.py` | `ContextProvider` abstract base, `ContextMode`, `Answer`, `Status` |
| `context/backend.py` | `ContextBackend` abstract I/O layer |
| `utils/events.py` | Event factory functions (`create_run_started_event`, etc.), `handle_event` |

---

*Analysis performed against Agno 2.6.9 source at `C:/Users/USER/Desktop/LBM Memry/venv/Lib/site-packages/agno`. All file:line citations reference the indexed version.*
