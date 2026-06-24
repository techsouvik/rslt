# Agno 2.6.9 — Tools System
**Subsystems:** tools/
**Codegraph:** 853 files, 17,055 nodes, 48,446 edges

---

## 1. Base Tool/Function/Toolkit Classes

### `Function` class
**File:** `tools/function.py:132`

`Function` is a Pydantic `BaseModel` that is the atomic unit of all tools. Key fields:

```python
class Function(BaseModel):
    name: str                               # Must match [a-z A-Z 0-9 _ -], max 64 chars
    description: Optional[str]
    parameters: Dict[str, Any]             # JSON Schema object; default {"type":"object","properties":{},"required":[]}
    strict: Optional[bool]                 # OpenAI strict mode
    instructions: Optional[str]            # Tool-specific system-prompt instructions
    add_instructions: bool = True          # Whether to inject instructions into system prompt
    entrypoint: Optional[Callable]         # The actual Python function
    skip_entrypoint_processing: bool       # Skip schema re-generation (set True for MCP/decorated toolkit methods)
    show_result: bool = False              # Print result alongside returning it to model
    stop_after_tool_call: bool = False     # Halt the agent loop after this tool executes
    pre_hook: Optional[Callable]          # Called before execution
    post_hook: Optional[Callable]         # Called after execution (always, even on failure)
    tool_hooks: Optional[List[Callable]]  # Middleware-style hook chain
    requires_confirmation: Optional[bool] # HITL: pause and ask user to confirm
    requires_user_input: Optional[bool]   # HITL: pause and collect user field values
    user_input_fields: Optional[List[str]]
    user_input_schema: Optional[List[UserInputField]]
    external_execution: Optional[bool]    # HITL: execution happens outside agent loop
    approval_type: Optional[str]          # "required" or "audit" (set by @approval decorator)
    cache_results: bool = False
    cache_dir: Optional[str]
    cache_ttl: int = 3600

    # Private runtime refs (not serialized)
    _agent: Optional[Any]
    _team: Optional[Any]
    _run_context: Optional[RunContext]
    _images / _videos / _audios / _files
```

**Important methods on `Function`:**
- `to_dict()` — serializes for API schema (name, description, parameters, strict, requires_confirmation, external_execution, approval_type)
- `from_callable(c, name, strict)` — class method, builds a `Function` from a bare callable (line 278)
- `process_entrypoint(strict)` — populates `parameters` by introspecting the callable's signature and type hints; also wraps it with `validate_call` (line 396)
- `_wrap_callable(func)` — wraps with Pydantic `validate_call` unless function has `agent`/`team` params or pydantic < 2.10 (line 562)
- `_get_cache_key`, `_get_cache_file_path`, `_get_cached_result`, `_save_to_cache` — cache helpers (lines 668–743)
- `process_schema_for_strict()` — recursively adds `additionalProperties: false` for OpenAI strict mode (line 612)

### `FunctionExecutionResult` class
**File:** `tools/function.py:746`
```python
class FunctionExecutionResult(BaseModel):
    status: Literal["success", "failure"]
    result: Optional[Any]
    error: Optional[str]
    updated_session_state: Optional[Dict[str, Any]]
    images / videos / audios / files: Optional[List[...]]
```

### `FunctionCall` class
**File:** `tools/function.py:760`
Wraps a `Function` with runtime call arguments and result. The main dispatch object that bridges model output to Python execution.

```python
class FunctionCall(BaseModel):
    function: Function
    arguments: Optional[Dict[str, Any]]
    result: Optional[Any]
    call_id: Optional[str]
    error: Optional[str]
```

### `ToolResult` class
**File:** `tools/function.py:757` (referenced at models/base.py:2228)
A structured return type tools can use to return both text and media artifacts.

### `Toolkit` class
**File:** `tools/toolkit.py:12`

All built-in tool collections extend `Toolkit`. It is NOT a Pydantic model — it is a plain Python class.

```python
class Toolkit:
    _requires_connect: bool = False   # DB/connection toolkits set this; Agent calls connect()/close() automatically

    def __init__(self,
        name: str,
        tools: Sequence[Union[Callable, Function]],
        async_tools: Optional[Sequence[tuple[Callable, str]]],
        instructions, add_instructions,
        include_tools, exclude_tools,
        requires_confirmation_tools, external_execution_required_tools,
        stop_after_tool_call_tools, show_result_tools,
        cache_results, cache_ttl, cache_dir,
        auto_register: bool = True,
    )

    self.functions: Dict[str, Function]        # sync functions
    self.async_functions: Dict[str, Function]  # async functions
```

Key methods:
- `register(function, name)` — registers a callable or `Function` object; auto-detects async via `iscoroutinefunction` (line 155)
- `_register_decorated_tool(function, name, is_async)` — handles `@tool`-decorated methods: re-binds `self`, merges decorator + toolkit-level settings (line 210)
- `get_functions()` — returns `self.functions` (sync dict) (line 306)
- `get_async_functions()` — returns merged dict where async variants override sync (line 314)
- `connect()` / `close()` — override in subclasses that need connection lifecycle management

---

## 2. `@tool` Decorator

**File:** `tools/decorator.py:87`

Converts a plain Python function or method into a `Function` object at decoration time.

**Valid kwargs:**
```
name, description, strict, instructions, add_instructions,
show_result, stop_after_tool_call,
requires_confirmation, requires_user_input, user_input_fields,
external_execution, external_execution_silent,
pre_hook, post_hook, tool_hooks,
cache_results, cache_dir, cache_ttl
```

**Mutual exclusivity rule (line 158–168):** Only one of `requires_user_input`, `requires_confirmation`, `external_execution` may be True simultaneously. Raises `ValueError` otherwise.

**Wrapper selection (line 204–209):**
- `isasyncgenfunction(func)` → `async_gen_wrapper`
- `_is_async_function(func)` → `async_wrapper`
- else → `sync_wrapper`

Each wrapper logs errors but re-raises them.

**Both `@tool` and `@tool(...)` forms work** (line 287–290): the decorator detects whether it was called directly on a function or with kwargs.

**Automatic behavior:** `stop_after_tool_call=True` implies `show_result=True` unless `show_result` is explicitly set to `False` (line 278–280).

**`@approval` decorator interaction (line 215–240):** A separate `@approval` decorator stamps `func._agno_approval_type` as a sentinel. When `@tool` sees this, it sets `approval_type` and auto-configures HITL flags. `approval_type="audit"` requires at least one HITL flag to already be set on `@tool`.

**Defaults at creation (line 249–283):**
```python
cache_results=False, cache_dir=None, cache_ttl=3600, add_instructions=True
```

After creating the `Function`, calls `function.process_entrypoint()` immediately to populate `parameters`.

---

## 3. Tool Registration on Agent

**File:** `agent/_tools.py:340` — `parse_tools(agent, tools, model, run_context, async_mode)`

Called every run from `determine_tools_for_model()` (line 472). Handles four input types:

| Input type | Handling |
|---|---|
| `dict` | Passed through as-is (built-in provider tools like web-search) |
| `Toolkit` | Calls `get_async_functions()` or `get_functions()`, deep-copies each `Function`, sets `_agent`, calls `process_entrypoint(strict)` |
| `Function` | Deep-copies, sets `_agent`, calls `process_entrypoint(strict)` |
| `callable` | Creates `Function.from_callable(tool, strict=strict)`, checks for `@approval` sentinel, deep-copies, sets `_agent` |

**Important behaviors:**
- Duplicate tool names are skipped with a `log_warning` (line 375–378, 404–407, 432–436)
- If `output_schema` is set AND `model.supports_native_structured_outputs`, all tools get `strict=True`
- `agent.tool_hooks` override individual function `tool_hooks` if set (line 390–391, 419–420, 461–463)
- `_func._run_context`, `_func._images`, `_func._files`, etc. are set in `determine_tools_for_model()` after the tool list is built (lines 509–513)
- Tool instructions (per-function `instructions`, per-toolkit `instructions`) are collected into `agent._tool_instructions` and injected into the system message

**API schema conversion:** `_format_tools()` in `models/base.py:598` wraps each `Function` as `{"type": "function", "function": tool.to_dict()}` and sorts the list deterministically by name to maximize prompt cache hits across providers (Anthropic, OpenAI, Gemini).

---

## 4. Tool Dispatch During a Run

Full call path (sync, non-streaming):

```
Agent.run()
  └── model.response(messages, tools=_functions)          [models/base.py:647]
        └── loop:
              _process_model_response(...)                 [provider-specific invoke()]
              assistant_message.tool_calls populated
              _prepare_function_calls(assistant_message, functions)  [models/base.py]
                  └── get_function_call(name, arguments, call_id, functions)  [utils/functions.py:10]
                        parses JSON arguments, normalizes "none"/"true"/"false" strings
                        returns FunctionCall(function=..., arguments=...)
              run_function_calls(function_calls, ...)       [models/base.py:2299]
                  └── for each fc:
                        HITL check → yield ModelResponse(event=tool_call_paused) if needed
                        run_function_call(fc, ...)           [models/base.py:2125]
                          yield ModelResponse(event=tool_call_started)
                          fc.execute()                       [tools/function.py:1019]
                            pre_hook()
                            cache check → return cached if hit
                            _build_nested_execution_chain() → execute entrypoint
                            cache save if success
                            post_hook() (always)
                          yield ModelResponse(event=tool_call_completed, tool_executions=[...])
                          function_call_results.append(result_message)
              format_function_call_results() → messages.extend(results)
              loop continues with updated messages
```

**Async path:** `arun_function_calls` runs all non-HITL calls concurrently via `asyncio.gather`, using `asyncio.to_thread(function_call.execute)` for sync functions (models/base.py:2450+).

---

## 5. Tool Result Handling

**`FunctionCall.execute()` returns `FunctionExecutionResult`** (tools/function.py:1019).

**`run_function_call()` in `models/base.py:2125`** converts the result into a `Message`:

- For **generators/iterators**: iterates the generator, accumulates string output, yields inner `RunOutputEvent` instances upstream (allows nested agent calls to bubble events)
- For **`ToolResult` instances**: extracts `.content` as the text result and transfers `.images/.videos/.audios/.files` to `FunctionExecutionResult`
- For **plain values**: `str(result)` conversion

**`create_function_call_result()` in `models/base.py:2075`** builds the `Message` (role=`tool`):
```python
Message(
    role=self.tool_message_role,   # "tool" for most providers
    content=output if success else function_call.error,
    tool_call_id=function_call.call_id,
    tool_name=function_call.function.name,
    tool_args=function_call.arguments,
    tool_call_error=not success,
    stop_after_tool_call=function_call.function.stop_after_tool_call,
    images/videos/audio/files=...,
)
```

**Result injection:** `format_function_call_results()` (models/base.py:2985) simply calls `messages.extend(function_call_results)`. Each provider may override this to adapt the format (e.g., Bedrock wraps results in `toolResult` objects).

**`AgentRunException` handling:** If the entrypoint raises `AgentRunException`, `execute()` stores the error string and `run_function_call()` calls `_handle_agent_exception()` which can inject additional messages or force `stop_after_tool_call=True` (models/base.py:2152–2157).

**`show_result`:** When `function_call.function.show_result` is True, `run_function_call` yields an extra `ModelResponse(content=function_call_output)` which surfaces the tool result as streaming content to the caller (models/base.py:2247–2248).

---

## 6. Built-in Tool Categories

152 files in `tools/`. Categories:

**Web / Search:**
`bravesearch`, `baidusearch`, `duckduckgo`, `exa`, `jina`, `linkup`, `perplexity`, `searxng`, `serpapi`, `serper`, `tavily`, `websearch`, `website`, `webtools`, `webbrowser`, `trafilatura`, `crawl4ai`, `firecrawl`, `scrapegraph`, `brightdata`, `spider`, `newspaper`, `newspaper4k`, `hackernews`, `llms_txt`

**Files / Storage:**
`file`, `local_file_system`, `csv_toolkit`, `file_generation`, `_local_file_utils`, `docling`

**Code / Execution:**
`coding`, `python`, `shell`, `e2b`, `daytona`, `docker`

**Databases:**
`duckdb`, `postgres`, `sql`, `redshift`, `neo4j`, `google/bigquery`

**Google Suite:**
`google/calendar`, `google/drive`, `google/gmail`, `google/sheets`, `google/slides`, `google/maps`, `google/auth`

**Communication:**
`email`, `gmail`, `slack`, `telegram`, `discord`, `webex`, `whatsapp`, `twilio`, `resend`, `aws_ses`, `zoom`, `cartesia`, `desi_vocal`

**Productivity / Project Management:**
`notion`, `jira`, `confluence`, `clickup`, `linear`, `trello`, `todoist`, `airflow`, `calcom`, `scheduler`

**AI / Media Generation:**
`dalle`, `fal`, `replicate`, `lumalab`, `models_labs`, `eleven_labs`, `mlx_transcribe`, `opencv`, `moviepy_video`, `nano_banana`, `visualization`, `cartesia`

**Finance / Data:**
`yfinance`, `openbb`, `financial_datasets`, `calculator`, `pandas`, `openweather`

**Cloud / APIs:**
`aws_lambda`, `api` (CustomApiTools), `shopify`, `salesforce`, `zendesk`, `apify`, `agentql`, `brandfetch`, `giphy`, `unsplash`, `reddit`, `x`, `spotify`, `youtube`, `arxiv`, `pubmed`, `wikipedia`, `github`, `gitlab`, `bitbucket`

**Memory / Knowledge:**
`mem0`, `memory`, `knowledge`, `zep`, `workspace`

**Reasoning / Control:**
`reasoning`, `sleep`, `parallel`, `user_control_flow`, `user_feedback`, `antigravity`

**Blockchain:**
`evm`

**MCP:**
`mcp/mcp.py`, `mcp/multi_mcp.py`, `mcp_toolbox.py`

**Models (AI providers as tools):**
`models/azure_openai`, `models/gemini`, `models/groq`, `models/morph`, `models/nebius`

**Streamlit:**
`streamlit/components.py`

---

## 7. MCP Tool Integration

**File:** `tools/mcp/mcp.py:29` — `MCPTools(Toolkit)`

**Three connection modes:**
1. `session=ClientSession(...)` — pre-initialized session
2. `command="npx -y @mcp-server/..."` + env → `stdio` transport (spawns subprocess)
3. `url="https://..."` → `streamable-http` (default) or `sse` transport

**Transport support:** `stdio`, `sse` (deprecated), `streamable-http`. URL implies streamable-http.

**Lifecycle:**
- `MCPTools` is used as an `async with` context manager: `__aenter__` calls `_connect()` → `initialize()` → `build_tools()`
- `build_tools()` (line 587): calls `session.list_tools()`, filters by `include_tools`/`exclude_tools`, for each tool creates a `Function` with `skip_entrypoint_processing=True` and the parameters pre-set from MCP's `inputSchema`
- The entrypoint for each MCP tool is a closure returned by `get_entrypoint_for_tool()` (`utils/mcp.py`) that calls `session.call_tool(name, arguments)`

**`header_provider` feature (line 55):** A callable that generates dynamic HTTP headers per agent run. `get_session_for_run(run_context, agent, team)` creates a per-`run_id` session with those headers. Sessions have 5-minute TTL and are cleaned up on `close()`.

**`refresh_connection=True`:** Forces a new MCP connection on each run.

**`MultiMCPTools`** (`tools/mcp/multi_mcp.py`): Aggregates multiple `MCPTools` instances into one toolkit.

**`MCPToolbox`** (`tools/mcp_toolbox.py`): Extends `MCPTools` with additional orchestration.

---

## 8. `cache_results` — How Tool Result Caching Works

Two independent implementations:

### A. Function-level cache (primary, used in production)
**File:** `tools/function.py:668–743`

Set via `@tool(cache_results=True)` or `Function(cache_results=True)` or `Toolkit(cache_results=True)`.

**Storage:** Filesystem at `{cache_dir}/functions/{function_name}/{md5_hash}.json`. Default `cache_dir` is `tempfile.gettempdir()/agno_cache`.

**Cache key** (`_get_cache_key`, line 668): MD5 of `f"{name}:{json.dumps(entrypoint_args_cleaned)}:{sorted(call_args)}"`. Framework-injected params (`agent`, `team`, `run_context`, media) are excluded from the key.

**TTL check** (`_get_cached_result`, line 706): Reads `{"timestamp": float, "result": any}` from JSON file, compares `time() - timestamp <= self.cache_ttl`. Expired files are deleted.

**Write** (`_save_to_cache`, line 733): If result is a Pydantic `BaseModel`, uses `.model_dump()` first.

**Not cached:** Generator/async generator results (checked via `isgeneratorfunction` at line 1034).

**Execution path** (`FunctionCall.execute()`, line 1019):
```
cache_results → _get_cache_key → _get_cache_file_path → _get_cached_result
  → HIT: return cached, skip entrypoint
  → MISS: execute, _save_to_cache, return result
```

### B. `cache_result` decorator (`utils/functions.py:74`)
An older/alternative decorator factory. Works similarly but checks `instance.cache_results` at runtime and uses `instance.cache_dir`/`instance.cache_ttl` if available. Used for methods where `Function`-level caching is not applied.

---

## 9. Tool Error Handling

**Argument parsing errors (`utils/functions.py:30–70`):** JSON parse failure → `ast.literal_eval` fallback → if both fail, `function_call.error` is set to a descriptive string; the `FunctionCall` is returned with `error` set (no exception raised). Non-dict JSON → similar error.

**Entrypoint execution errors (`tools/function.py:1087–1096`):**
- `AgentRunException`: re-raised after setting `self.error`, which allows the agent loop to inject extra messages via `_handle_agent_exception()`
- Any other `Exception`: `log_warning` + `log_exception`, stored in `self.error`, returns `FunctionExecutionResult(status="failure", error=str(e))`

**Hook errors (`tools/function.py:855–860, 882–888`):** Both `pre_hook` and `post_hook` swallow non-`AgentRunException` errors (log warning + log exception, execution continues). This ensures `post_hook` always runs even if `pre_hook` or the entrypoint fails.

**`_safe_hook_call` (line 801):** Protects the live `messages` list by passing a shallow copy to hooks, restoring the live reference after. Prevents hooks from corrupting message list structure.

**`@tool` decorator error (decorator.py:174–181):** Wraps entrypoint in `sync_wrapper`/`async_wrapper` that logs the exception before re-raising it. Errors in the decorator wrapper always propagate.

**`run_function_call()` exception boundary (models/base.py:2159–2161):** Non-`AgentRunException` errors from `fc.execute()` are re-raised after logging, which terminates the agent run.

**Tool call limit (models/base.py:2115–2123, 2313–2317):** When `tool_call_limit` is exceeded, `create_tool_call_limit_error_result()` creates a `Message` telling the model "Tool call limit reached. Don't try again." and the tool is skipped (not executed).

---

## 10. Async Tool Support

**Detection:** `iscoroutinefunction(func)` and `isasyncgenfunction(func)` throughout. The `_is_async_function()` helper in `decorator.py:12` also checks `__wrapped__`, `__code__.co_flags`, and `__func__` to handle edge cases like `@staticmethod`.

**Toolkit registration:** `Toolkit.register()` auto-detects async at registration time. Async functions go to `self.async_functions`, sync to `self.functions`. `get_async_functions()` merges both with async variants taking precedence — allows providing an optimized async implementation of a sync tool.

**Explicit async variants:** Pass `async_tools=[(self.method, "tool_name")]` to `Toolkit.__init__`. Used when async method names differ from sync names.

**`parse_tools()` (agent/_tools.py:346):** Accepts `async_mode: bool` which selects `get_async_functions()` or `get_functions()` from each toolkit.

**`arun_function_call()` (models/base.py:2450):** For async execution:
- If entrypoint is a coroutine/async gen: `await function_call.aexecute()`
- If any `tool_hooks` are async: `await function_call.aexecute()`
- Otherwise (sync function in async context): `await asyncio.to_thread(function_call.execute)` — runs sync tool in thread pool

**`FunctionCall.aexecute()` (tools/function.py:1227):** Async counterpart to `execute()`, handles async generators via async iteration, calls `await function_call.function.entrypoint(**args)` for coroutines.

**`pydantic < 2.10.0` caveat (tools/function.py:573–578):** `validate_call` is NOT applied to coroutines on older pydantic. The function is returned unwrapped. This means runtime type validation is silently skipped for async tools on older pydantic.

---

## 11. Tool Input Validation

**Schema generation** occurs in `process_entrypoint()` (tools/function.py:396) and `from_callable()` (line 278). Both call `get_json_schema()` in `utils/json_schema.py:209`.

**`get_json_schema(type_hints, param_descriptions, strict)`:**
- Iterates filtered type hints (excluding `agent`, `team`, `run_context`, `self`, media params, and framework-typed params like `my_agent: Agent`)
- Strips `Optional[X]` wrappers (they are handled in `required` determination, not schema type)
- Calls `get_json_schema_for_arg(type_hint)` per parameter

**`get_json_schema_for_arg()` (utils/json_schema.py:120) type mapping:**

| Python type | JSON Schema |
|---|---|
| `Literal[...]` | `{"type":"string/integer/boolean/number","enum":[...]}` |
| `List[X]`, `Tuple[X]`, `Set[X]` | `{"type":"array","items":...}` |
| `Dict[K,V]` | `{"type":"object","propertyNames":...,"additionalProperties":...}` |
| `Optional[X]` / `Union[X,None]` | `{"anyOf":[...]}` |
| `Enum` subclass | `{"type":"string","enum":[member.value,...]}` |
| Pydantic `BaseModel` | `model_json_schema()` inlined via `inline_pydantic_schema()` |
| `@dataclass` | Converts fields recursively to object schema |
| `int` | `integer` |
| `float`/`complex`/`Decimal` | `number` |
| `str` | `string` |
| `bool` | `boolean` |
| `list/tuple/set/frozenset` | `array` |
| `dict/mapping` | `object` |
| Unknown | `object` (fallback) |

**`inline_pydantic_schema()`:** Resolves all `$ref` and `$defs` in Pydantic-generated schemas to produce a fully inlined JSON Schema (no `$ref` in the final output).

**`required` determination:**
- Non-strict: parameters with `param.default == param.empty` (no default value)
- Strict mode: ALL parameters are marked required (OpenAI requirement for strict mode)

**Runtime validation:** `Function._wrap_callable()` wraps the entrypoint with `pydantic.validate_call(config=dict(arbitrary_types_allowed=True))`. Skipped for: async generators, pydantic < 2.10 + coroutines, functions with `agent`/`team` params (by name or type annotation), already-wrapped functions.

**Argument pre-processing (`utils/functions.py:50–66`):** Before Pydantic validation, string values of `"none"`/`"null"` → `None`, `"true"` → `True`, `"false"` → `False`, other strings are `.strip()`ped.

---

## 12. `show_tool_calls` — Tool Call Visibility

Agno does NOT have a single `show_tool_calls` flag. Visibility is instead controlled at multiple levels:

### `show_result` on `Function` / `@tool`
**File:** `tools/function.py:157` and `tools/decorator.py:67`

When `show_result=True`, `run_function_call()` (models/base.py:2247) yields an extra `ModelResponse(content=function_call_output)` after the tool executes. This content surfaces as streaming content in the agent's response. Automatically set to `True` when `stop_after_tool_call=True`.

### `stream_events=True` on agent run
**File:** `agent/agent.py:322`

When `stream_events=True` is passed to `agent.run()` or `agent.arun()`, the agent yields `ToolCallStartedEvent` and `ToolCallCompletedEvent` as part of the event stream.

- `ToolCallStartedEvent` (run/agent.py:415): emitted when `ModelResponseEvent.tool_call_started` is received; includes `ToolExecution` with `tool_name`, `tool_args`
- `ToolCallCompletedEvent` (run/agent.py:421): includes `ToolExecution` with result, `tool_call_error`, metrics (timer, duration, start/end timestamps)

These events are yielded at `agent/_response.py:1569–1576` (started) and similar locations for completed.

### `events_to_skip` on Agent
**File:** `agent/agent.py` — agents can set `events_to_skip` to filter out specific event types from the stream.

### `store_events` on Agent
Whether tool events are persisted to storage.

### Logging
`log_debug(f"Running: {self.get_call_str()}")` is always called at the start of `FunctionCall.execute()` (tools/function.py:1026). `get_call_str()` formats `function_name(key=value, ...)` with terminal-width-aware truncation.

---

## Summary: Full Tool Lifecycle

```
@tool decorator
  → creates Function, calls process_entrypoint() immediately
  → Function.parameters = JSON Schema from type hints + docstring

Agent(tools=[...])
  → stored as-is; not processed at construction time

agent.run() / agent.arun()
  → determine_tools_for_model()
    → parse_tools(): deep-copies Functions, sets _agent/_run_context/media refs,
                     calls process_entrypoint(strict) for Toolkit-registered tools
  → _format_tools(): wraps as {"type":"function","function":{...}}, sorts by name

model.response() / model.aresponse()
  → sends tool schemas to LLM API
  → LLM returns tool_calls in assistant_message
  → _prepare_function_calls(): parses tool_call JSON → FunctionCall objects
  → run_function_calls() [sync] / arun_function_calls() [async]
    → HITL check → pause if confirmation/user_input/external needed
    → run_function_call():
        emit tool_call_started event
        FunctionCall.execute():
          pre_hook()
          cache check
          tool_hooks chain → entrypoint(**args)
          cache save
          post_hook()
        convert result → Message(role="tool")
        emit tool_call_completed event
  → format_function_call_results(): messages.extend(tool_messages)
  → loop back to LLM with updated messages
  → break when no more tool calls or stop_after_tool_call
```
