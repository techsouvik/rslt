# Agno 2.6.9 — Teams & Workflows
**Subsystems:** team/, workflow/, factory/, agents/

---

## Table of Contents
1. [Team — Overview & Construction](#1-team--overview--construction)
2. [TeamMode — All Four Modes](#2-teammode--all-four-modes)
3. [How `run()` / `arun()` Work](#3-how-run--arun-work)
4. [run_dispatch — The Entry Gate](#4-run_dispatch--the-entry-gate)
5. [The delegate_task_to_member Tool — Core of Routing & Coordination](#5-the-delegate_task_to_member-tool--core-of-routing--coordination)
6. [Mode-Specific Behavior: route vs coordinate vs broadcast vs tasks](#6-mode-specific-behavior-route-vs-coordinate-vs-broadcast-vs-tasks)
7. [Member Selection Logic](#7-member-selection-logic)
8. [Shared Context Between Members](#8-shared-context-between-members)
9. [Session State in Teams — `session_state` vs `team_session_state`](#9-session-state-in-teams--session_state-vs-team_session_state)
10. [Team Streaming](#10-team-streaming)
11. [Workflow — Overview & Construction](#11-workflow--overview--construction)
12. [Workflow vs Team — Key Differences](#12-workflow-vs-team--key-differences)
13. [Workflow `run()` Method](#13-workflow-run-method)
14. [Workflow `session_state` Persistence](#14-workflow-session_state-persistence)
15. [Agents Inside Workflows — Step](#15-agents-inside-workflows--step)
16. [Workflow Caching](#16-workflow-caching)
17. [Workflow Streaming](#17-workflow-streaming)
18. [RunEvent / WorkflowRunEvent Types](#18-runevent--workflowrunevent-types)
19. [factory/ — BaseFactory and Purpose](#19-factory--basefactory-and-purpose)
20. [agents/ vs agent/ — The Distinction](#20-agents-vs-agent--the-distinction)

---

## 1. Team — Overview & Construction

**Source:** `team/team.py:72–674`

`Team` is a `@dataclass(init=False)` class. Its `__init__` takes a large parameter list and delegates entirely to `_init.__init__(self, ...)` (`team/team.py:552`). The actual construction logic is in `team/_init.py`.

### Required constructor parameters
```python
Team(
    members: Union[List[Union[Agent, "Team"]], Callable[..., List]],
    ...
)
```
`members` is the only positionally-required argument. Everything else is keyword-optional.

### Key constructor fields (team/team.py:77–397)

| Field | Type | Default | Purpose |
|---|---|---|---|
| `members` | `List[Agent\|Team]\|Callable` | — | The member agents/sub-teams |
| `model` | `Optional[Model]` | `None` | The leader's LLM |
| `mode` | `Optional[TeamMode]` | `None` | Execution mode (see §2) |
| `respond_directly` | `bool` | `False` | Return member's response without leader synthesis |
| `delegate_to_all_members` | `bool` | `False` | Broadcast to all members |
| `determine_input_for_members` | `bool` | `True` | If False, sends raw input to members |
| `max_iterations` | `int` | `10` | Max iterations for `tasks` mode |
| `session_state` | `Optional[Dict]` | `None` | Persisted across runs via DB |
| `add_session_state_to_context` | `bool` | `False` | Inject session_state into system prompt |
| `enable_agentic_state` | `bool` | `False` | Give leader an `update_session_state` tool |
| `share_member_interactions` | `bool` | `False` | Send previous delegation results to subsequent members |
| `add_team_history_to_members` | `bool` | `False` | Send team-level chat history to each member |
| `stream_member_events` | `bool` | `True` | Stream member events upstream |
| `store_member_responses` | `bool` | `False` | Embed member RunOutputs in team RunOutput |
| `cache_callables` | `bool` | `True` | Cache results of `Callable[..., List]` factories |

The `__init__` body ends by calling `_init.__init__(...)` and then setting two component metadata fields:
```python
# team/team.py:675-676
self._version: Optional[int] = None
self._stage: Optional[str] = None
```

---

## 2. TeamMode — All Four Modes

**Source:** `team/mode.py:1–22`

```python
class TeamMode(str, Enum):
    coordinate = "coordinate"   # line 12
    route      = "route"        # line 16
    broadcast  = "broadcast"    # line 19
    tasks      = "tasks"        # line 22
```

### Definitions

**`coordinate` (default supervisor pattern)**
> "Leader picks members, crafts tasks, synthesizes responses."

The leader model calls `delegate_task_to_member(member_id, task)` one or more times, collects the results as tool call outputs, then synthesizes a final response. This is the default when `mode` is unset and `members` are present.

**`route` (specialist routing)**
> "Leader routes to a specialist and returns the member's response directly."

The leader calls `delegate_task_to_member` for exactly one member. If `respond_directly=True` the member's raw response becomes the team's response — no leader synthesis pass. If `respond_directly=False` the leader still produces a synthesis but typically only delegates to one member.

**`broadcast` (send-to-all)**
> "Leader delegates the same task to all members simultaneously."

Equivalent to setting `delegate_to_all_members=True`. The leader calls `delegate_task_to_member` once per member with the same task, collects all results, then synthesizes.

**`tasks` (autonomous task loop)**
> "Leader decomposes goals into a shared task list, delegates tasks to members, and loops until all work is complete."

The leader gets **task management tools** (not `delegate_task_to_member`). It iterates up to `max_iterations` times, maintaining a task list in `run_context.session_state`. Loop ends when `task_list.goal_complete` or `task_list.all_terminal()`.

---

## 3. How `run()` / `arun()` Work

**Source:** `team/team.py:748–963`

Both are overloaded (Literal `stream=False/True` overloads) and delegate immediately to `_run.run_dispatch` / `_run.arun_dispatch`:

```python
# team/team.py:829
def run(self, input, *, stream=None, ...) -> ...:
    return _run.run_dispatch(self, input=input, stream=stream, ...)

# team/team.py:938
def arun(self, input, *, stream=None, ...) -> ...:
    return _run.arun_dispatch(self, input=input, stream=stream, ...)
```

Return types:
- `stream=False` → `TeamRunOutput`
- `stream=True` → `Iterator[Union[RunOutputEvent, TeamRunOutputEvent]]`
- `arun stream=False` → `Coroutine[Any, Any, TeamRunOutput]`
- `arun stream=True` → `AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]]`

---

## 4. run_dispatch — The Entry Gate

**Source:** `team/_run.py:1761–1949`

`run_dispatch` is the synchronous entry point. Steps in order:

1. **Reject async DB** — `_has_async_db(team)` raises if sync run() is called with an async DB (`team/_run.py:1793`).
2. **Generate run_id** — `run_id = run_id or str(uuid4())` (`team/_run.py:1797`).
3. **`team.initialize_team(debug_mode=debug_mode)`** — sets `team.id`, initialises LearningMachine, etc.
4. **Validate input** against `team.input_schema`.
5. **Register run** — `register_run(run_id)` for cancellation tracking (`team/_run.py:1818`).
6. **Normalize hooks** — `normalize_pre_hooks` / `normalize_post_hooks`.
7. **`_initialize_session`** — resolves `session_id` and `user_id`.
8. **Validate media** — `validate_media_object_id`.
9. **Create `TeamRunInput`** — wraps validated input + media.
10. **`_read_or_create_session`** — loads `TeamSession` from DB or creates new.
11. **`_update_metadata`** — merges DB metadata into `team.metadata`.
12. **`resolve_run_options`** — resolves stream, yield_run_output, history flags.
13. **`_initialize_session_state`** + **`_load_session_state`** — merges DB state with call-time state (DB state wins except where `overwrite_db_session_state=True`).
14. **Create `RunContext`** — holds run_id, session_id, user_id, session_state, dependencies, knowledge_filters, metadata, output_schema.
15. **`_resolve_run_dependencies`** — executes any `Callable` dependencies now.
16. **`get_response_format`** — determines structured output schema for the model.
17. **Create `TeamRunOutput`** — the response accumulator.
18. **Start `RunMetrics` timer**.
19. **Dispatch** to `_run_stream` (if `opts.stream`) or `_run` (otherwise).

---

## 5. The delegate_task_to_member Tool — Core of Routing & Coordination

**Source:** `team/_default_tools.py:384–675`

This is the key mechanism by which the leader delegates work. It is a **generator function** (yields events or strings) created by `_get_delegate_task_function(...)`.

### Tool signature exposed to the LLM
```python
def delegate_task_to_member(member_id: str, task: str) -> Iterator[...]:
    """Use this function to delegate a task to the selected team member.
    You must provide a clear and concise description of the task the member
    should achieve AND the expected output.
    """
```

### Execution flow (`team/_default_tools.py:538–674`)

1. **`_find_member_by_id(team, member_id, run_context)`** — looks up the member by ID in the team's `resolved_members` list. Returns `(index, member_agent)` or `None` if not found (with error string yield).

2. **`_setup_delegate_task_to_member(member_agent, task)`** — initialises the member, copies `respond_directly` output schema down, handles `determine_input_for_members=False` (uses raw input), attaches team history and member interaction context, loads per-member history for `add_history_to_context`.

3. **Member run** — calls `member_agent.run(...)` with:
   - Same `session_id` as the team (shared session)
   - A **copy** of `run_context.session_state` (so member changes don't pollute the team state until merged)
   - `stream=True/False` matching the team's stream flag
   - `yield_run_output=True` in stream mode to capture the final `RunOutput`

4. **Stream path** (`team/_default_tools.py:563–600`): iterates the member's event stream, attaches `parent_run_id`, yields member events upstream. Captures final `RunOutput` from `yield_run_output`.

5. **HITL check** — if `member_agent_run_response.is_paused`, calls `_propagate_member_pause` and returns early with a pause message.

6. **Non-stream path** — returns member content string (or model_dump_json for Pydantic, JSON for other types).

7. **`_process_delegate_task_to_member`** — post-processing:
   - Sets `parent_run_id` on the member run
   - Updates team-level `team_run_context` with this interaction
   - Appends member run to `run_response.member_runs` if `store_member_responses=True`
   - Calls `session.upsert_run(member_agent_run_response)`
   - **Merges member's mutated session_state copy back into `run_context.session_state`** via `merge_dictionaries` (`team/_default_tools.py:532`)
   - Updates team media from member output

---

## 6. Mode-Specific Behavior: route vs coordinate vs broadcast vs tasks

### `coordinate` and `route` (same code path)

Both use `_run` / `_run_stream`. The difference is only in what the leader LLM *decides* to do. The leader's system prompt lists all members with their IDs, names, descriptions, and tools. The leader calls `delegate_task_to_member` zero or more times.

- `respond_directly=True`: output schema is propagated to the selected member. The member's response is returned as-is. Leader doesn't synthesize.
- `determine_input_for_members=False`: raw user input goes to the member instead of a leader-crafted task.

### `broadcast`

`delegate_to_all_members=True` is how broadcast is implemented. In `_tools.py` (`_determine_tools_for_model`), when `delegate_to_all_members=True`, the leader is essentially forced or instructed to delegate to every member. The leader still calls `delegate_task_to_member` multiple times (once per member).

### `tasks` (autonomous loop)

**Source:** `team/_run.py:175–483` (sync), `team/_run.py:486–961` (stream)

When `team.mode == TeamMode.tasks`, `_run` immediately dispatches to `_run_tasks`:
```python
# team/_run.py:1010
if team.mode == TeamMode.tasks:
    return _run_tasks(team, ...)
```

In `_run_tasks`:
- **No `delegate_task_to_member` tool** is added.
- Instead, **task management tools** are added via `_get_task_management_tools(...)` (from `team/_task_tools.py`). These include: `create_task`, `assign_task`, `mark_task_complete`, `mark_all_complete`, `update_task`, etc.
- The task list lives in `run_context.session_state["task_list"]`.
- The loop injects current task state as a user message on iterations > 0 (`team/_run.py:309–318`):
  ```python
  state_message = Message(
      role="user",
      content=f"<current_task_state>\n{task_summary}\n</current_task_state>\n\n"
              "Continue working on the tasks..."
  )
  ```
- Loop terminates when `task_list.goal_complete` or `task_list.all_terminal()` (with no failures).
- Warning logged if `max_iterations` reached without completion.

---

## 7. Member Selection Logic

**Source:** `team/_tools.py:_find_member_by_id` (referenced in `_default_tools.py:550`)

`_find_member_by_id(team, member_id, run_context)` searches `get_resolved_members(team, run_context)` — the list of members after resolving any callable factory. It matches by member `id` attribute. Returns `(index, member)` tuple or `None`.

The members list description in the system prompt is built by `get_members_system_message_content` (`team/_messages.py:76–141`):
```python
# team/_messages.py:91
content += f'<member id="{member_id}" name="{member.name}" type="team">\n'
# For agents:
# member id, name, description, role, tools list
```

Sub-teams are shown with their nested members indented inside `<member>` tags.

---

## 8. Shared Context Between Members

Members share context through several mechanisms:

### 8a. Shared session_id (`team/_default_tools.py:567,607`)
Every `member_agent.run(...)` call receives `session_id=session.session_id` — the team's session ID. This means all member agents read/write to the same DB session row, but their individual conversation turns are stored as separate sub-runs via `session.upsert_run(member_agent_run_response)`.

### 8b. session_state copy-then-merge (`team/_default_tools.py:561,532`)
```python
member_session_state_copy = copy(run_context.session_state)
# ... member runs with this copy ...
merge_dictionaries(run_context.session_state, member_session_state_copy)
```
The member receives a **shallow copy** of the team's current `session_state`. After the member run, the copy (potentially mutated by the member) is merged back into the team's `session_state`.

### 8c. team_run_context (interaction log, `team/_default_tools.py:499–511`)
`add_interaction_to_team_run_context(team_run_context, member_name, task, run_response)` appends each member's task+result to an in-memory dict. If `share_member_interactions=True`, subsequent members receive this interaction log in their task context via `_determine_team_member_interactions`.

### 8d. Team history (`team/_default_tools.py:453–456`)
If `add_team_history_to_members=True`, `session.get_team_history_context(num_runs=team.num_team_history_runs)` is fetched and prepended to each member's task.

### 8e. dependencies
`run_context.dependencies` is passed through to every member call (`team/_default_tools.py:577`).

---

## 9. Session State in Teams — `session_state` vs `team_session_state`

There is **no `team_session_state` field** in the current codebase. This was apparently an older API name. The current field is uniformly called `session_state`.

### How `session_state` works in Teams

**Source:** `team/_storage.py:_load_session_state`, `team/_run.py:1863–1871`

1. **At construction**: `Team(session_state={...})` sets the default in-memory state.
2. **At run time**: `_initialize_session_state(team, session_state=call_time_state, ...)` merges call-time state with the team's default.
3. **DB load**: `_load_session_state(team, session=team_session, session_state=...)` loads from `session.session_data["session_state"]`. Merge precedence: **call_time > DB_state > constructor_default** (unless `overwrite_db_session_state=True`).
4. **In RunContext**: `run_context.session_state` is the live working copy for the entire run.
5. **Persistence**: After each run, `_cleanup_and_store` → `session.upsert_run(run_response)` → `team.save_session(session)` saves the state back. Before saving, system keys (`current_session_id`, `current_user_id`, etc.) are stripped.

### Special keys injected automatically (`team/_init.py:_initialize_session_state`)
```
workflow_id, workflow_name, current_user_id, current_session_id, current_run_id
```

### `enable_agentic_state` (`team/_tools.py:205–206`)
When `True`, a `update_session_state` tool is added to the leader:
```python
Function(name="update_session_state", entrypoint=partial(_update_session_state_tool, team))
```
This lets the leader LLM directly mutate `run_context.session_state` at runtime (`team/_default_tools.py:172–187`).

---

## 10. Team Streaming

**Source:** `team/_run.py:1316–1758`

`_run_stream` is an `Iterator` generator. It follows the same 13-step pipeline as `_run` but:
- Each step that can stream **yields events** instead of collecting them.
- `stream_events=True` activates protocol events (`RunStartedEvent`, `ToolCallStartedEvent`, `RunCompletedEvent`, etc.).
- `stream_events=False` only streams **content chunks** (`RunContentEvent`).
- Member events are yielded from `delegate_task_to_member` directly upstream (`team/_default_tools.py:600`): `yield member_agent_run_output_event`.
- `yield_run_output=True` causes the final `TeamRunOutput` object itself to be yielded at the end of the stream (needed by workflow step executor to capture the complete output).
- `stream_member_events=True` (default) means member agent/team events flow through. Setting `False` suppresses them.

### Stream event classes (`run/team.py:190–528`)

All extend `BaseTeamRunEvent(BaseRunOutputEvent)` with fields: `team_id`, `team_name`, `run_id`, `parent_run_id`, `session_id`, `workflow_id`, `workflow_run_id`, `step_id`, `step_name`, `step_index`, `nested_depth`.

Key events:
- `RunStartedEvent` — first event, includes `model`, `model_provider`
- `RunContentEvent` — content delta
- `IntermediateRunContentEvent` — intermediate delegation results
- `RunContentCompletedEvent` — content stream complete
- `RunCompletedEvent` — includes `member_responses`, `session_state`, `metrics`
- `RunPausedEvent` — HITL pause with `tools` and `requirements`
- `TaskIterationStartedEvent` / `TaskIterationCompletedEvent` — tasks mode
- `ToolCallStartedEvent` / `ToolCallCompletedEvent` / `ToolCallErrorEvent`
- `ModelRequestStartedEvent` / `ModelRequestCompletedEvent`

---

## 11. Workflow — Overview & Construction

**Source:** `workflow/workflow.py:332–476`

`Workflow` is a plain `@dataclass` with a manual `__init__`. It represents a **pipeline** of `Step` objects (or a callable function).

### Constructor
```python
Workflow(
    id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    steps: Optional[WorkflowSteps] = None,   # core field
    agent: Optional[WorkflowAgent] = None,   # agentic mode
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    ...
)
```

### `steps` type alias (`workflow/workflow.py:309–329`)
```python
WorkflowSteps = Union[
    Callable[["Workflow", WorkflowExecutionInput], Union[StepOutput, ...]],  # single callable
    Steps,                                                                    # Steps container
    List[Union[Callable, Step, Steps, Loop, Parallel, Condition, Router, "Workflow"]]
]
```

Three forms:
1. **Callable** — a single function `f(workflow, execution_input, **kwargs)`. Can be sync, generator, async, or async generator.
2. **`Steps`** container — a named group of steps.
3. **List** — explicit list of step components, iterated in order.

### Step type registry (`workflow/workflow.py:126–133`)
```python
STEP_TYPE_MAPPING = {
    Step: StepType.STEP,
    Steps: StepType.STEPS,
    Loop: StepType.LOOP,
    Parallel: StepType.PARALLEL,
    Condition: StepType.CONDITION,
    Router: StepType.ROUTER,
}
```

### Key constructor fields

| Field | Purpose |
|---|---|
| `steps` | The pipeline definition |
| `db` | Session persistence (required for state across runs) |
| `session_state` | Default state, deepcopy'd into new sessions |
| `stream` / `stream_events` | Default streaming config |
| `stream_executor_events` | Whether to forward agent/team events |
| `store_executor_outputs` | Save agent/team responses in WorkflowRunOutput |
| `add_workflow_history_to_steps` | Send previous run history to each step |
| `num_history_runs` | How many history runs to send (default 3) |
| `overwrite_db_session_state` | If True, call-time state wins over DB state |
| `input_schema` | Pydantic model for input validation |
| `dependencies` | Merged with run-time dependencies and passed downstream |

---

## 12. Workflow vs Team — Key Differences

| Dimension | Team | Workflow |
|---|---|---|
| **Mental model** | Leader agent orchestrates sub-agents via LLM tool calls | Deterministic pipeline of Steps executed in sequence |
| **Orchestration** | LLM (the leader) decides who to call and what task | Code decides (Step list, Condition, Loop, Router) |
| **Members** | `List[Agent\|Team]`, callable factory | Each `Step` has one `agent` OR `team` OR `executor` callable |
| **Routing** | LLM-driven (`delegate_task_to_member`) | Code-driven (`Condition`, `Router`, `Loop`, `Parallel`) |
| **State** | `session_state` in `RunContext`, shared across members | `session_state` in `RunContext`, shared across steps |
| **Session** | `TeamSession` | `WorkflowSession` |
| **Nested** | Teams can be members of teams | Workflows can be steps in workflows (`Step(workflow=w)`) |
| **History** | `add_team_history_to_members` | `add_workflow_history_to_steps` |
| **Streaming** | Team yields `TeamRunOutputEvent` | Workflow yields `WorkflowRunOutputEvent` |
| **HITL** | Via tool HITL on member agents (`RunPausedEvent`) | Per-step: `requires_confirmation`, `requires_output_review`, `requires_user_input`, `on_error=pause` |
| **Main use case** | Complex open-ended tasks requiring LLM judgment | Structured, repeatable pipelines with predictable flow |

---

## 13. Workflow `run()` Method

**Source:** `workflow/workflow.py:8559–8719`

```python
def run(
    self,
    input: Optional[Union[str, Dict, List, BaseModel]] = None,
    ...
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    session_state: Optional[Dict[str, Any]] = None,
    ...
) -> Union[WorkflowRunOutput, Iterator[WorkflowRunOutputEvent]]:
```

### Execution sequence (`workflow/workflow.py:8582–8719`)

1. **Reject async DB** for sync run.
2. **Register run** for cancellation tracking.
3. **`_set_debug()`** — sets log level, propagates to steps.
4. **`initialize_workflow()`** — auto-generates `self.id` from name if unset.
5. **`_initialize_session(session_id, user_id)`** — auto-generates session_id if unset, makes it sticky to the instance.
6. **`read_or_create_session`** — loads `WorkflowSession` from DB or creates new with deepcopy of `self.session_state`.
7. **`_load_session_state`** — merges DB state with call-time state (DB > call-time unless `overwrite_db_session_state`).
8. **`_initialize_session_state`** — injects `workflow_id`, `workflow_name`, `current_user_id`, `current_session_id`, `current_run_id`.
9. **Resolve stream flags** — `stream = stream or self.stream or False`. `stream_events` forced to False if `stream=False`.
10. **`_prepare_steps()`** — prepares step objects.
11. **Create `WorkflowExecutionInput`** — wraps input + media.
12. **`update_agents_and_teams_session_info()`** — propagates session/user ID to all embedded agents/teams.
13. **`_resolve_run_params`** — deep-merges `dependencies` (call-time > self.dependencies) and `metadata`.
14. **Create `RunContext`** — includes `workflow_id`, `workflow_name`.
15. **Check for `self.agent`** — if a `WorkflowAgent` is configured, dispatches to `_execute_workflow_agent` (agentic workflow mode).
16. **Create `WorkflowRunOutput`**.
17. **Start `WorkflowMetrics` timer**.
18. **Dispatch** to `_execute_stream` (stream=True) or `_execute` (stream=False).

### `_execute` — the synchronous step runner (`workflow/workflow.py:1946–2230`)

For list-of-steps mode:
- Maintains `previous_step_outputs: Dict[str, StepOutput]` and `collected_step_outputs: List`.
- Maintains shared media lists (`shared_images`, `shared_videos`, `shared_audio`, `shared_files`) — each step's output media is appended and forwarded to the next step.
- Per step: `step.execute(step_input, session_id=..., run_context=..., ...)`.
- HITL check **before** execution via `step_pause_status`.
- Error policies (`on_error`): `fail` (re-raise), `skip` (create `StepOutput(success=False)`), `pause` (HITL).
- Executor-level HITL check **after** execution: `is_executor_pause(step_output)`.
- Output review check: `check_output_review_status`.
- Early termination: `if step_output.stop: break`.
- After all steps: aggregates metrics, sets `workflow_run_response.content = last_output.content` (unwraps nested steps to get deepest content).
- `session.upsert_run(run=workflow_run_response)` + `self.save_session(session=session)` in `finally` block.

---

## 14. Workflow `session_state` Persistence

**Source:** `workflow/workflow.py:1513–1540`, `workflow/workflow.py:1380–1400`

### Loading
```python
def _load_session_state(self, session: WorkflowSession, session_state: Dict[str, Any]):
    if session.session_data and "session_state" in session.session_data:
        session_state_from_db = session.session_data["session_state"]
        if session_state_from_db and not self.overwrite_db_session_state:
            # DB state merged in, then run_params applied on top
            merged_state = session_state_from_db.copy()
            merge_dictionaries(merged_state, session_state)  # call-time wins on conflict
            session_state.clear()
            session_state.update(merged_state)
    session.session_data["session_state"] = session_state
    return session_state
```

Merge precedence: **call-time > DB** (unless `overwrite_db_session_state=True`, in which case call-time completely replaces DB state).

### Saving
```python
# workflow/workflow.py:1380–1394
def save_session(self, session: WorkflowSession) -> None:
    if self.db is not None and session.session_data is not None:
        # Strip ephemeral keys before saving
        if session.session_data.get("session_state") is not None:
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)
            session.session_data["session_state"].pop("workflow_id", None)
            session.session_data["session_state"].pop("run_id", None)
            session.session_data["session_state"].pop("session_id", None)
            session.session_data["session_state"].pop("workflow_name", None)
        result = self._upsert_session(session=session)
```

The ephemeral "system" keys are stripped before persistence so they don't pollute the stored state.

### Accessing state across runs
```python
# Between runs:
wf = Workflow(db=my_db, ...)
result1 = wf.run(input="step 1", session_id="abc")
result2 = wf.run(input="step 2", session_id="abc")  # loads DB state from run 1
```

The `session_state` dict is available to:
- Step executors via `run_context.session_state`
- Custom callable steps via `session_state=self.session_state` parameter (`workflow/workflow.py:2917`)
- Any agent/team in a Step that receives `add_session_state_to_context=True`

---

## 15. Agents Inside Workflows — Step

**Source:** `workflow/step.py:72–250`

A `Step` wraps one executor. Exactly one of these should be set:

```python
@dataclass
class Step:
    agent:    Optional[Agent]      = None  # step.py:79
    team:     Optional[Team]       = None  # step.py:80
    executor: Optional[StepExecutor] = None  # callable
    workflow: Optional["Workflow"] = None   # nested workflow
```

### Step execution via `step.execute(step_input, ...)`

The `execute` method:
1. Detects executor type (agent, team, function, or nested workflow).
2. For agents: calls `agent.run(input=step_input.input, session_id=session_id, run_context=run_context, ...)`.
3. For teams: calls `team.run(input=step_input.input, session_id=session_id, run_context=run_context, ...)`.
4. Wraps result in a `StepOutput`.

### StepInput data flow (`workflow/workflow.py:2001–2009`)
```python
step_input = self._create_step_input(
    execution_input=execution_input,
    previous_step_outputs=previous_step_outputs,  # all prior steps' results
    shared_images=shared_images,
    ...
)
```
Each step receives the original workflow input **plus** outputs of all preceding steps via `step_input.previous_step_outputs`.

### HITL on Steps (`workflow/types.py:63–131`)
Step supports full HITL via `HumanReview` config or direct fields:
- `requires_confirmation` — pause before execution
- `requires_user_input` — collect input before execution
- `requires_output_review` — pause after execution for review
- `on_error`: `fail`, `skip`, or `pause`
- `on_reject`: `skip`, `cancel`, `else` (Condition only), `retry`

---

## 16. Workflow Caching

### Session caching (`workflow/workflow.py:1215–1251`)
```python
if workflow_session is not None and self.cache_session:
    self._workflow_session = workflow_session
```
When `cache_session=True`, the loaded `WorkflowSession` is stored in `self._workflow_session`. Subsequent calls to `read_or_create_session` for the same `session_id` return the cached object immediately, skipping the DB read.

### Step-level caching
There is no built-in step result caching in the Workflow core. Each `step.execute()` call always runs. Caching of individual agent calls would have to be handled at the Agent level (e.g., agent-level response caching if supported by the LLM provider, or by the caller caching `StepOutput`).

### Callable factory caching (Team, not Workflow)
Teams support callable factory caching for `tools`, `knowledge`, `members` via `cache_callables=True` and `_callable_tools_cache`, `_callable_knowledge_cache`, `_callable_members_cache` (`team/team.py:391–427`). Workflows themselves do not have this mechanism — their step list is static.

---

## 17. Workflow Streaming

**Source:** `workflow/workflow.py:2232–2738` (sync), async version at `workflow/workflow.py:3050+`

`_execute_stream` is a sync `Iterator[WorkflowRunOutputEvent]`.

### Event enrichment (`workflow/workflow.py:1694–1751`)
Every event from a step executor is enriched via `_enrich_event_with_workflow_context`:
- Sets `workflow_id`, `workflow_name`, `workflow_run_id`, `session_id` on the event.
- For nested workflows: detects `event.workflow_id != workflow_run_response.workflow_id` → increments `nested_depth`, preserves original `workflow_id`, sets `parent_step_id`.
- Sets `step_id`, `step_name`, `step_index` (only if not already set — preserves parallel.py's tuple indices).

### Event routing
- `isinstance(event, StepOutput)` → transform to `StepOutputEvent`, yield (for function executors only, not agents/teams since their content flows through content events).
- `isinstance(event, WorkflowRunOutputEvent)` → enrich and yield via `_handle_event`.
- Other events (agent `RunContentEvent`, team `TeamRunContentEvent`) → enrich and yield if `stream_executor_events=True`.

### WebSocket support (`workflow/workflow.py:1579–1691`)
`_handle_event` buffers events via `event_buffer.add_event(run_id, event)` and broadcasts via `websocket_manager.broadcast_to_run(run_id, json_str)`. This supports reconnecting clients.

### Async streaming
`_aexecute_stream` (`workflow/workflow.py:3050+`) is the async version — uses `step.aexecute_stream(...)` and `async for event in step.aexecute_stream(...)`.

---

## 18. RunEvent / WorkflowRunEvent Types

### `TeamRunEvent` — Team events (`run/team.py` referenced from `team/team.py:44`)

All team events are values of the `TeamRunEvent` str-enum. Key values:
- `run_started`, `run_content`, `run_intermediate_content`, `run_content_completed`, `run_completed`
- `run_error`, `run_cancelled`, `run_paused`, `run_continued`
- `tool_call_started`, `tool_call_completed`, `tool_call_error`
- `reasoning_started`, `reasoning_step`, `reasoning_content_delta`, `reasoning_completed`
- `memory_update_started`, `memory_update_completed`
- `session_summary_started`, `session_summary_completed`
- `model_request_started`, `model_request_completed`
- `compression_started`, `compression_completed`
- `followups_started`, `followups_completed`
- `task_iteration_started`, `task_iteration_completed` (tasks mode only)
- `pre_hook_started/completed`, `post_hook_started/completed`
- `parser_model_response_started/completed`, `output_model_response_started/completed`

### `WorkflowRunEvent` — Workflow events (`run/workflow.py:38–79`)

```python
class WorkflowRunEvent(str, Enum):
    workflow_started      = "WorkflowStarted"
    workflow_completed    = "WorkflowCompleted"
    workflow_cancelled    = "WorkflowCancelled"
    workflow_error        = "WorkflowError"
    step_started          = "StepStarted"
    step_completed        = "StepCompleted"
    step_paused           = "StepPaused"
    step_continued        = "StepContinued"
    step_executor_paused  = "StepExecutorPaused"
    step_executor_continued = "StepExecutorContinued"
    step_output_review    = "StepOutputReview"
    step_error            = "StepError"
    loop_execution_started / loop_iteration_started / loop_iteration_completed / loop_execution_completed
    parallel_execution_started / parallel_execution_completed
    condition_execution_started / condition_execution_completed / condition_paused
    router_execution_started / router_execution_completed / router_paused
    steps_execution_started / steps_execution_completed
    step_output           = "StepOutput"
    custom_event          = "CustomEvent"
```

### Base event class (`run/workflow.py:82–148`)

`BaseWorkflowRunOutputEvent(BaseRunOutputEvent)` carries:
```python
workflow_id:    Optional[str]
workflow_name:  Optional[str]
session_id:     Optional[str]
run_id:         Optional[str]
step_id:        Optional[str]
parent_step_id: Optional[str]
nested_depth:   int  # 0=top-level, 1=first nested, etc.
```

### `WorkflowRunOutput`
The top-level result object. Key fields:
- `run_id`, `session_id`, `user_id`, `workflow_id`, `workflow_name`
- `input` — the original input
- `content` — final content (from last step's deepest output)
- `step_results: List[StepOutput]` — all step outputs
- `step_executor_runs` — agent/team RunOutput objects (for HITL continue_run)
- `status: RunStatus` (running / completed / error / cancelled / paused)
- `metrics: WorkflowMetrics` — per-step metrics dict + total duration
- `paused_step_index`, `paused_step_name`, `error_requirements` — HITL state

---

## 19. factory/ — BaseFactory and Purpose

**Source:** `factory/base.py:1–120`

```python
class BaseFactory(Generic[T]):
    def __init__(
        self,
        id: str,                      # stable API URL handle (required)
        db: Union[BaseDb, AsyncBaseDb], # required for session storage
        factory: Callable[[RequestContext], T],  # the builder function
        name: Optional[str] = None,
        description: Optional[str] = None,
        input_schema: Optional[Type[BaseModel]] = None,
    ):
```

**Purpose**: A `BaseFactory` wraps a callable that builds an `Agent`, `Team`, or `Workflow` **per request**. AgentOS invokes the factory with a `RequestContext` (containing auth info, factory_input, etc.) on every API call, getting back a fresh component.

This is the correct pattern for **per-user or per-request component customization** — e.g., injecting user-specific tools, knowledge bases, or config at runtime.

### `RequestContext` (`factory/utils.py`)
Carries: `user_id`, `session_id`, `factory_input` (validated against `input_schema`), any other request-level metadata.

### Subclasses
- `AgentFactory` (in `agent/factory.py`) — produces `Agent`
- `TeamFactory` (in `team/factory.py`) — produces `Team`
- `WorkflowFactory` (in `workflow/factory.py`) — produces `Workflow`

Each subclass is thin — just narrows the `T` type parameter and provides the specific component type.

### invoke / ainvoke
```python
def invoke(self, ctx: RequestContext) -> T:    # sync
async def ainvoke(self, ctx: RequestContext) -> T:  # async
```
`invoke` validates that the factory is not async. `ainvoke` handles both async and sync factories (wraps sync in `asyncio.to_thread`).

---

## 20. agents/ vs agent/ — The Distinction

There is **no `agents/` (plural) directory** in the agno package. The file tree shows only `agent/` (singular).

The distinction in the codebase is:

| Path | Purpose |
|---|---|
| `agent/agent.py` | The `Agent` class — a single conversational agent |
| `agent/factory.py` | `AgentFactory(BaseFactory[Agent])` — per-request factory |
| `agent/remote.py` | `RemoteAgent` — proxy to an agent running on a remote AgentOS server |
| `agent/protocol.py` | `AgentProtocol` — abstract interface for things that behave like an agent |

The `agent/` module is the single-agent building block. The `team/` module is the multi-agent layer built on top of it. There is no separate `agents/` folder.

---

## Key Practical Notes for LBM

### Teams
- **COORDINATE mode is the default** — just pass `members=[...]` and the leader will call `delegate_task_to_member` using LLM judgment.
- **session_state is shared across all members** via the copy-merge mechanism. Members can mutate it. Use `enable_agentic_state=True` on the team to let the leader also update it via tool.
- **`share_member_interactions=True`** is the flag to give each subsequent member context about what earlier members said. Without it, members are isolated.
- **MCP tools only work with `arun()`** — sync `run()` path does not refresh MCP connections (noted in `team/_run.py:1062`).
- **`cache_callables=False` is needed** when your tools/knowledge/members factory depends on `run_context` and must not be cached across calls (per memory note `feedback_agno_api_usage.md`).

### Workflows
- **`session_state` persists across sequential `.run()` calls** on the same `session_id` — this is the primary state carry mechanism for multi-turn workflows.
- **Step output flows to next step** via `step_input.previous_step_outputs` — steps can explicitly read prior step results.
- **`stream_executor_events=True`** (default) — agent/team internal events bubble up through the workflow stream. Set to `False` for a cleaner stream with only workflow-level events.
- **`overwrite_db_session_state=False`** (default) — DB state takes precedence. To reset state per run, pass explicit `session_state={}` with `overwrite_db_session_state=True`.
