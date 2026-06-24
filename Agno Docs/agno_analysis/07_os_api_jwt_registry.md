# Agno 2.6.9 — Agent OS, API, JWT & Registry
**Subsystems:** os/, api/, client/, registry/, remote/

---

## 1. Agent OS (`os/`)

### What "Agent OS" Means

`AgentOS` is Agno's primary server runtime. It wraps a FastAPI application that serves
agents, teams, and workflows as REST + WebSocket + SSE endpoints. The conceptual role is
an operating system for agents: it manages registrations, lifecycle, routing, middleware,
and inter-component communication in a single `FastAPI` instance.

Source: `os/app.py:192` — `class AgentOS`

### Constructor signature (key args)

```python
# os/app.py:193
class AgentOS:
    def __init__(
        self,
        id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        agents: Optional[List[Union[Agent, RemoteAgent, AgentProtocol, AgentFactory]]] = None,
        teams: Optional[List[Union[Team, RemoteTeam, TeamFactory]]] = None,
        workflows: Optional[List[Union[Workflow, RemoteWorkflow, WorkflowFactory]]] = None,
        knowledge: Optional[List[Knowledge]] = None,
        interfaces: Optional[List[BaseInterface]] = None,
        a2a_interface: bool = False,
        authorization: bool = False,
        authorization_config: Optional[AuthorizationConfig] = None,
        cors_allowed_origins: Optional[List[str]] = None,
        config: Optional[Union[str, AgentOSConfig]] = None,
        settings: Optional[AgnoAPISettings] = None,
        lifespan: Optional[Any] = None,
        enable_mcp_server: bool = False,
        base_app: Optional[FastAPI] = None,
        on_route_conflict: Literal["preserve_agentos", "preserve_base_app", "error"] = "preserve_agentos",
        tracing: bool = False,
        auto_provision_dbs: bool = True,
        run_hooks_in_background: bool = False,
        telemetry: bool = True,
        registry: Optional[Registry] = None,
        scheduler: bool = False,
        scheduler_poll_interval: int = 15,
        scheduler_base_url: Optional[str] = None,
        internal_service_token: Optional[str] = None,
    )
```

At least one of `agents`, `teams`, `workflows`, `knowledge`, or `db` must be provided
(`os/app.py:259`).

### Initialization Sequence

`__init__` calls, in order (`os/app.py:326-342`):
1. `_initialize_agents()` — injects `db`, tracks MCP tools, calls `agent.initialize_agent()`,
   sets `agent.store_events = True`, propagates `run_hooks_in_background`.
2. `_initialize_teams()` — same for teams, recursively initializes nested members.
3. `_initialize_workflows()` — same for workflows; generates ID from name if missing.
4. `_populate_registry()` — inserts all code-defined agents and teams into `self.registry`
   so DB-loaded workflows can rehydrate their steps.
5. `_raise_if_duplicate_ids()` — guards against ID collisions across agents/teams/workflows.
6. Optional: `_setup_tracing()` if `tracing=True`.
7. Optional: sends `OSLaunch` telemetry to `https://os-api.agno.com`.

### `get_app()` — The FastAPI Builder (`os/app.py:682`)

Returns a fully configured `FastAPI` instance. It:

- Creates a `FastAPI` app (or adopts `base_app` if supplied) with combined lifespans:
  - user lifespan
  - MCP tools lifespan (connect/close per MCP tool)
  - `db_lifespan` — provisions DBs on startup, closes on shutdown
  - `scheduler_lifespan` (if `scheduler=True`) — starts `SchedulePoller`
  - `http_client_lifespan` — closes default httpx clients
- Calls `_add_built_in_routes(app)` to wire all routers
- Calls `_auto_discover_databases()` and `_auto_discover_knowledge_instances()`
- Adds all domain routers (sessions, memory, evals, metrics, knowledge, traces, database)
- Conditionally adds: components, schedules, approvals (require `db`), registry
  (requires `registry`)
- Mounts MCP server at `/` if `enable_mcp_server=True`
- Applies CORS middleware via `update_cors_middleware`

### Lifespan Composition (`os/app.py:145-166`)

Multiple lifespan context managers are composed by a nested recursive combiner:

```python
def _combine_app_lifespans(lifespans: list) -> Any:
    @asynccontextmanager
    async def combined_lifespan(app):
        async def _run_nested(index: int):
            if index >= len(lifespans):
                yield
                return
            async with lifespans[index](app):
                async for _ in _run_nested(index + 1):
                    yield
        async for _ in _run_nested(0):
            yield
    return combined_lifespan
```

### OS Interfaces (`os/interfaces/`)

Pluggable server-side integrations. Available: A2A, AG-UI, Slack, Telegram, WhatsApp.
Each implements `BaseInterface` (`os/interfaces/base.py`) with a `get_router()` method.

- **A2A** (`os/interfaces/a2a/`) — Agent-to-Agent interop protocol; exposes agents/teams
  via a standard JSON-RPC or REST interface. Enabled via `a2a_interface=True` on AgentOS
  or by including an `A2A()` object in `interfaces`.
- **AG-UI** (`os/interfaces/agui/`) — streaming UI protocol.
- **Slack/Telegram/WhatsApp** — external messaging platform adapters with their own
  event routers and security verification.

### Resync (`os/app.py:372`)

`AgentOS.resync(app)` re-discovers all components and re-provisions all routers in-place
(hot-reload). Used for Studio's live-code editing mode.

### MCP Server Integration (`os/mcp.py`)

When `enable_mcp_server=True`, `get_mcp_server(os)` creates a FastMCP instance exposing
all agent/team/workflow run endpoints as MCP tools, plus `config()` as an MCP resource.
Mounted at `/` alongside normal routes.

### Scheduler (`os/app.py:112-142`)

When `scheduler=True`:
- An `internal_service_token` is auto-generated (`secrets.token_urlsafe(32)`) if not supplied.
- `scheduler_lifespan` starts a `SchedulePoller` (polls DB every N seconds) driving a
  `ScheduleExecutor` that calls `POST /agents/*/runs`, `POST /workflows/*/runs`, etc.
- The executor authenticates to the OS using the internal token, which is granted
  `INTERNAL_SERVICE_SCOPES` in `os/auth.py:17-27`.

---

## 2. API Server (`os/routers/`)

### Router Map

All main routers are wired in `_add_built_in_routes` (`os/app.py:450`) and `get_app()`
(`os/app.py:763`):

| Router factory | Path prefix | Tag | Condition |
|---|---|---|---|
| `get_home_router` | `/` | Core | always |
| `get_health_router` | `/health` | Core | always |
| `get_info_router` | `/info` | Core | always |
| `get_base_router` | `/config`, `/models` | Core | always |
| `get_agent_router` | `/agents` | Agents | always |
| `get_team_router` | `/teams` | Teams | always |
| `get_workflow_router` | `/workflows` | Workflows | always |
| `get_websocket_router` | `/ws` | WebSocket | always |
| `get_session_router` | `/sessions` | Sessions | always |
| `get_memory_router` | `/memories` | Memory | always |
| `get_eval_router` | `/eval-runs` | Evals | always |
| `get_metrics_router` | `/metrics` | Metrics | always |
| `get_knowledge_router` | `/knowledge` | Knowledge | always |
| `get_traces_router` | `/traces` | Traces | always |
| `get_database_router` | `/databases` | Database | always |
| `get_components_router` | `/components` | Components | requires sync `BaseDb` |
| `get_schedule_router` | `/schedules` | Schedules | requires `db` |
| `get_approval_router` | `/approvals` | Approvals | requires `db` |
| `get_registry_router` | `/registry` | Registry | requires `registry` |
| Interface routers | custom prefix | Interface | each added interface |

Disabled features return 503 via `_get_disabled_feature_router` (`os/app.py:169-189`).

### Agent Endpoints (`os/routers/agents/router.py`)

```
GET    /agents                    list all agents (filtered by JWT scopes)
GET    /agents/{agent_id}         get agent config
POST   /agents/{agent_id}/runs    run agent (form data: message, session_id, ...)
  ?stream=true                    returns StreamingResponse (SSE)
  ?background=true                returns SSE from detached background task
POST   /agents/{agent_id}/runs/{run_id}/continue   resume a paused run (HITL)
POST   /agents/{agent_id}/runs/{run_id}/cancel     cancel a running execution
GET    /agents/{agent_id}/runs/{run_id}/status     check run status
GET    /agents/{agent_id}/runs/{run_id}/events     replay buffered SSE events
```

Run endpoint accepts form data (NOT JSON). Key form fields: `message`, `session_id`,
`user_id`, `stream`, `stream_events`, `background`, and optional JSON-encoded fields
for `images`, `audio`, `video`, `files`, `session_state`, `dependencies`, `metadata`,
`knowledge_filters`.

### SSE Streaming

`agent_response_streamer` (`os/routers/agents/router.py:78`) — inline async generator.
Calls `agent.arun(stream=True, stream_events=True)` and yields `format_sse_event(chunk)`.
Cancelled on client disconnect (`asyncio.CancelledError`).

`agent_resumable_response_streamer` (`os/routers/agents/router.py:138`) — used when
`background=True`. The agent runs in a detached `asyncio.Task`; events are buffered in
`event_buffer` and published to `sse_subscriber_manager` for reconnecting clients.

### Base Router Endpoints (`os/router.py:51`)

```
GET /config   — returns ConfigResponse (agents, teams, workflows, db, memory, etc.)
GET /models   — returns List[Model] (unique models from all agents/teams)
```

The base router applies `get_authentication_dependency(settings)` to all routes as a
router-level dependency (`os/router.py:67`).

### WebSocket Router (`os/router.py:get_websocket_router`)

Workflow WebSocket endpoint at `/ws/workflows/{workflow_id}/{session_id}` for streaming
workflow execution over a persistent WS connection. JWT validation done inline via
`app.state.jwt_validator`.

### `api/` — Agno Cloud API Client (separate from AgentOS)

This is distinct from the OS-hosted API. `api/api.py` contains `Api` (an httpx wrapper)
that points to `https://os-api.agno.com` (configured via `api/settings.py:19`). Used
for telemetry (`api/agent.py`, `api/os.py`) and workspace-level operations. Not a
server; purely a client for Agno's cloud service.

---

## 3. JWT & Authentication

### Layer 1 — `JWTValidator` (`os/middleware/jwt.py:36`)

Core validation class, usable standalone (e.g. WebSocket handlers).

```python
# os/middleware/jwt.py:67
class JWTValidator:
    def __init__(
        self,
        verification_keys: Optional[List[str]] = None,  # static public keys / secrets
        jwks_file: Optional[str] = None,                # path to JWKS JSON file
        algorithm: str = "RS256",
        validate: bool = True,
        scopes_claim: str = "scopes",
        user_id_claim: str = "sub",
        session_id_claim: str = "session_id",
        audience_claim: str = "aud",
        leeway: int = 10,
    )
```

Key resolution order (`os/middleware/jwt.py:108-130`):
1. `verification_keys` param
2. `JWT_VERIFICATION_KEY` env var (appended if not already present)
3. `jwks_file` param → `JWT_JWKS_FILE` env var

Validation logic (`os/middleware/jwt.py:176`):
- JWKS keys tried first by `kid` header; falls back to `_default` key.
- Each static key tried in order; first success wins.
- If `expected_audience` provided, manually verifies `aud` claim after decode.
- Returns `{"user_id", "session_id", "scopes", "audience"}` via `extract_claims()`.

### Layer 2 — `JWTMiddleware` (`os/middleware/jwt.py:316`)

Starlette `BaseHTTPMiddleware`. Full RBAC middleware.

```python
# os/middleware/jwt.py:394
class JWTMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        verification_keys: Optional[List[str]] = None,
        jwks_file: Optional[str] = None,
        algorithm: str = "RS256",
        validate: bool = True,
        authorization: Optional[bool] = None,   # enables scope enforcement
        token_source: TokenSource = TokenSource.HEADER,  # HEADER | COOKIE | BOTH
        token_header_key: str = "Authorization",
        cookie_name: str = "access_token",
        scopes_claim: str = "scopes",
        user_id_claim: str = "sub",
        session_id_claim: str = "session_id",
        audience_claim: str = "aud",
        audience: Optional[Union[str, Iterable[str]]] = None,
        verify_audience: bool = False,
        dependencies_claims: Optional[List[str]] = None,
        session_state_claims: Optional[List[str]] = None,
        scope_mappings: Optional[Dict[str, List[str]]] = None,
        excluded_route_paths: Optional[List[str]] = None,
        admin_scope: Optional[str] = None,
        user_isolation: bool = False,          # opt-in per-user DB isolation
    )
```

On each request (`dispatch`):
1. Checks `excluded_route_paths` (`/`, `/health`, `/info`, `/docs`, etc.) — skip if matched.
2. Extracts token from header (`Bearer <token>`) or cookie based on `token_source`.
3. Calls `self.validator.validate_token(token, expected_audience)`.
4. Calls `self.validator.extract_claims(payload)`.
5. Stores on `request.state`: `user_id`, `session_id`, `scopes`, `authenticated=True`,
   `authorization_enabled`, `user_isolation_enabled`, `admin_scope`.
6. If `authorization=True` (RBAC): looks up required scopes for `METHOD /path` in
   `scope_mappings` (built from `get_default_scope_mappings()` merged with user overrides),
   then calls `has_required_scopes()`. Returns 403 on failure.
7. No token → 401 (if RBAC enabled) or skips (validation-only mode).

Default excluded routes (`os/middleware/jwt.py:535-545`):
```python
["/", "/health", "/info", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]
```

### Layer 3 — Security Key Authentication (`os/auth.py:62`)

Fallback for non-JWT setups. `get_authentication_dependency(settings)` creates a FastAPI
dependency applied at the base router level (`os/router.py:67`).

Decision tree (`os/auth.py:78-113`):
1. If `settings.authorization_enabled` → skip (JWT handles it).
2. If `request.state.authenticated` is already `True` → skip.
3. If `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE` env var set → skip.
4. If `settings.os_security_key` not set → skip (open access).
5. If internal service token matches (`hmac.compare_digest`) → grant internal scopes.
6. Otherwise verify `credentials.credentials == settings.os_security_key`; 401 on mismatch.

`OS_SECURITY_KEY` is a simpler pre-shared-secret mechanism (non-JWT), suitable for
single-tenant deployments.

### Layer 4 — RBAC Scopes (`os/scopes.py`)

`AgentOSScope` enum (only one named constant defined, rest are string-format):
```python
class AgentOSScope(str, Enum):
    ADMIN = "agent_os:admin"   # os/scopes.py:82
```

Scope format (`os/scopes.py:1-23`):
- `resource:action` — global resource scope (e.g. `agents:read`)
- `resource:<id>:action` — per-resource scope (e.g. `agents:web-agent:run`)
- `resource:*:action` — wildcard resource scope (e.g. `agents:*:run`)
- `agent_os:admin` — full access

Legacy alias: `system` → `config` (`os/scopes.py:31-33`).

`get_default_scope_mappings()` (`os/scopes.py:386`) defines all 60+ endpoint→scope
mappings covering agents, teams, workflows, sessions, memories, knowledge, metrics,
evals, traces, schedules, approvals, databases, registry, and components.

Core scope evaluation (`os/scopes.py:231`):
```python
def has_required_scopes(
    user_scopes: List[str],
    required_scopes: List[str],
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    admin_scope: Optional[str] = None,
) -> bool
```

Called in:
- `os/middleware/jwt.py` (dispatch) — route-level RBAC
- `os/auth.py` (approval check) — approval gate
- `os/router.py` — via `get_authentication_dependency`

### Layer 5 — User Isolation (`os/middleware/user_scope.py`)

Opt-in per-user data scoping (enabled via `user_isolation=True` on `JWTMiddleware` or
`AuthorizationConfig`).

`get_scoped_user_id(request)` (`os/middleware/user_scope.py:78`):
- Returns `None` if `user_isolation_enabled=False` (default — preserves backwards compat).
- Returns `None` if no `user_id` in JWT.
- Returns `None` if user has admin scope (admins see all data).
- Returns `user_id` for non-admin authenticated users when isolation is enabled.

`resolve_db_and_scope(request, dbs, ...)` (`os/middleware/user_scope.py:116`) — endpoint
utility returning `(db, user_id)` tuple. Non-admin scoped users get their JWT sub as
`user_id`; admins/unscoped get the `fallback_user_id` query param.

`enforce_owner_on_entity(request, entity)` (`os/middleware/user_scope.py:176`) — coerces
`entity.user_id` to JWT sub for non-admin callers on writes.

### How Auth Is Applied to Routes

```
Request → CORSMiddleware
        → JWTMiddleware.dispatch()         (extracts + validates JWT, stores in request.state)
        → FastAPI Dependency injection:
            get_authentication_dependency() (security key fallback)
            require_resource_access("agents", "run", "agent_id")  (per-route RBAC dep)
            require_approval_resolved(db)  (approval gate on /continue)
        → Route handler
```

`require_resource_access` (`os/auth.py:303`) is a dependency factory that reads the
resource ID from path params and calls `check_resource_access(request, id, type, action)`.
No-ops when `request.state.authorization_enabled` is `False`.

---

## 4. `client/` — AgentOSClient

### `AgentOSClient` (`client/os.py:72`)

HTTP client for talking to a running AgentOS instance. Used both by `RemoteAgent` /
`RemoteTeam` / `RemoteWorkflow` internally, and directly in user code.

```python
# client/os.py:80
class AgentOSClient:
    def __init__(self, base_url: str, timeout: float = 60.0)
```

No API key management at the client level — auth tokens are passed per-call as `headers`
(`Optional[Dict[str, str]]`). The caller supplies `{"Authorization": "Bearer <token>"}`.

Transport: uses shared `httpx` clients from `agno.utils.http.get_default_sync_client()`
and `get_default_async_client()` (connection pool, not recreated per request).

Methods (selection):

| Method | HTTP | Endpoint |
|---|---|---|
| `get_config()` / `aget_config()` | GET | `/config` |
| `get_models()` | GET | `/models` |
| `list_agents()` | GET | `/agents` |
| `get_agent(agent_id)` / `aget_agent(agent_id)` | GET | `/agents/{id}` |
| `run_agent(agent_id, message, ...)` | POST (form) | `/agents/{id}/runs` |
| `run_agent_stream(...)` | POST (form) | `/agents/{id}/runs` — SSE |
| `continue_agent_run(...)` | POST | `/agents/{id}/runs/{run_id}/continue` |
| `continue_agent_run_stream(...)` | POST | `/agents/{id}/runs/{run_id}/continue` — SSE |
| `cancel_agent_run(...)` | POST | `/agents/{id}/runs/{run_id}/cancel` |
| `list_teams()` / `run_team(...)` / `run_team_stream(...)` | — | `/teams/...` |
| `list_workflows()` / `run_workflow(...)` / `run_workflow_stream(...)` | — | `/workflows/...` |
| `get_sessions()` / `create_session()` / `delete_session()` | — | `/sessions/...` |
| `list_memories()` / `create_memory()` / `delete_memory()` | — | `/memories/...` |
| `search_knowledge(query, ...)` / `upload_knowledge_content(...)` | — | `/knowledge/...` |
| `get_traces()` / `search_traces()` / `get_trace_session_stats()` | — | `/traces/...` |
| `list_eval_runs()` / `run_eval(...)` / `delete_eval_runs(...)` | — | `/eval-runs/...` |
| `get_metrics()` / `refresh_metrics()` | — | `/metrics/...` |
| `migrate_database(db_id)` | POST | `/databases/{id}/migrate` |

Streaming (`_astream_post_form_data`) uses `httpx` async streaming; SSE lines are parsed
by `_parse_sse_events()` (`client/os.py:366`) which strips `data: ` prefix and parses JSON,
yielding typed event objects via a provided `event_parser` callable.

Error handling: `ConnectError`/`ConnectTimeout` → `RemoteServerUnavailableError`;
`TimeoutException` → `RemoteServerUnavailableError`.

### A2A Client (`client/a2a/`)

`A2AClient` (`client/a2a/client.py`) supports the Agent-to-Agent protocol (JSON-RPC or
REST). Used when `protocol="a2a"` on `RemoteAgent`/`RemoteTeam`. Methods:
`send_message()`, `stream_message()`, `get_agent_card()` (fetches
`/.well-known/agent.json`).

---

## 5. `registry/` — Component Registry

### `Registry` (`registry/registry.py:22`)

A dataclass (not a service, not a DB-backed store) that holds **non-serializable
in-process objects** needed to rehydrate Workflow steps loaded from the database.

```python
@dataclass
class Registry:
    name: Optional[str] = None
    description: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid4()))
    tools: List[Any] = field(default_factory=list)
    models: List[Model] = field(default_factory=list)
    dbs: List[BaseDb] = field(default_factory=list)
    vector_dbs: List[VectorDb] = field(default_factory=list)
    schemas: List[Type[BaseModel]] = field(default_factory=list)
    functions: List[Callable] = field(default_factory=list)
    agents: List[Agent] = field(default_factory=list)
    teams: List[Team] = field(default_factory=list)
```

Key methods:

```python
# registry/registry.py:56
def rehydrate_function(self, func_dict: Dict[str, Any]) -> Function:
    """Reconstruct a Function from dict, reattaching its entrypoint."""
    func = Function.from_dict(func_dict)
    func.entrypoint = self._entrypoint_lookup.get(func.name)
    return func

# registry/registry.py:62
def get_schema(self, name: str) -> Optional[Type[BaseModel]]
def get_db(self, db_id: str) -> Optional[BaseDb]
def get_function(self, name: str) -> Optional[Callable]
def get_agent(self, agent_id: str) -> Optional[Agent]
def get_team(self, team_id: str) -> Optional[Team]
def get_agent_ids(self) -> Set[str]
def get_team_ids(self) -> Set[str]
def get_all_component_ids(self) -> Set[str]
```

`_entrypoint_lookup` is a `@cached_property` (`registry/registry.py:41`) that builds a
name→callable dict by walking all `Toolkit` functions and standalone `Function` objects.

### How Registration Works

`AgentOS._populate_registry()` (`os/app.py:617`) auto-populates the registry with all
code-defined agents and teams:

```python
def _populate_registry(self) -> None:
    if self.registry is None:
        self.registry = Registry()
    # Agents
    existing_agent_ids = {getattr(a, "id", None) for a in self.registry.agents}
    for agent in self._agents:
        agent_id = getattr(agent, "id", None)
        if agent_id is not None and agent_id not in existing_agent_ids:
            self.registry.agents.append(agent)
    # Teams (same pattern)
```

### Registry HTTP Endpoint (`os/routers/registry/registry.py`)

`GET /registry` — returns a `RegistryContentResponse` list describing all registered
components (tools, models, DBs, schemas, functions, agents, teams) as JSON metadata.
Only enabled when `registry` is passed to `AgentOS`. Requires scope `registry:read`.

Resource types (`os/schema.py:721`):
```python
class RegistryResourceType(str, Enum):
    TOOL = "tool"
    MODEL = "model"
    DB = "db"
    VECTOR_DB = "vector_db"
    SCHEMA = "schema"
    FUNCTION = "function"
    AGENT = "agent"
    TEAM = "team"
```

Metadata schemas (`os/schema.py:734-815`): `CallableMetadata`, `ToolMetadata`,
`ModelMetadata`, `DbMetadata`, `VectorDbMetadata`, `SchemaMetadata`, `FunctionMetadata`
— each captures `class_path`, parameters JSON schema, signatures, etc. for discovery
and Studio integration.

---

## 6. `remote/` — Remote Execution

### `BaseRemote` (`remote/base.py:363`)

Base class for `RemoteAgent`, `RemoteTeam`, `RemoteWorkflow`. Manages protocol selection
and TTL-cached configuration.

```python
@dataclass
class BaseRemote:
    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        protocol: Literal["agentos", "a2a"] = "agentos",
        a2a_protocol: Literal["json-rpc", "rest"] = "rest",
        config_ttl: float = 300.0,      # 5 minutes TTL on cached config
    )
```

On init (`remote/base.py:405-410`):
- `protocol="agentos"` → creates `AgentOSClient(base_url, timeout)`
- `protocol="a2a"` → creates `A2AClient(base_url, ...)`

Config caching (`remote/base.py:446-464`):
- `_config` property fetches `GET /config` on first access, caches with TTL.
- `refresh_os_config()` force-refreshes.

Auth token forwarding (`remote/base.py:474-498`):
```python
def _get_headers(self, auth_token: Optional[str] = None) -> Dict[str, str]:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers

def _get_auth_headers(self, auth_token: Optional[str] = None) -> Optional[Dict[str, str]]:
    if auth_token:
        return {"Authorization": f"Bearer {auth_token}"}
    return None
```

### `RemoteAgent` (`agent/remote.py:36`)

Concrete remote agent. Inherits `BaseRemote`. Agent-config also cached with TTL.

```python
def __init__(
    self,
    base_url: str,
    agent_id: str,
    timeout: float = 60.0,
    protocol: Literal["agentos", "a2a"] = "agentos",
    a2a_protocol: Literal["json-rpc", "rest"] = "rest",
    config_ttl: float = 300.0,
)
```

`arun()` dispatch logic (`agent/remote.py:259-351`):
1. Validate and serialize input.
2. Get auth headers from `auth_token` param.
3. If `a2a_client` → call `_arun_a2a()` which maps `session_id` → `context_id`.
4. If `agentos_client`:
   - `stream=True` → `agentos_client.run_agent_stream(...)` — returns `AsyncIterator`
   - `stream=False` → `agentos_client.run_agent(...)` — returns `RunOutput`

`acontinue_run()` (`agent/remote.py:463`) — continues a paused (HITL) run; calls
`continue_agent_run_stream()` or `continue_agent_run()`.

`acancel_run(run_id)` (`agent/remote.py:505`) — calls `cancel_agent_run()`; returns bool.

`get_agent_config()` (`agent/remote.py:70`):
- A2A path: fetches `/.well-known/agent.json`, returns minimal `AgentResponse`.
- AgentOS path: calls `agentos_client.aget_agent(agent_id)`.

`db` property (`agent/remote.py:171`) — constructs `RemoteDb` from config if agent has
a `db_id`; `RemoteDb` delegates all session/memory/trace operations back to
`AgentOSClient`.

### `RemoteDb` (`remote/base.py:47`)

Thin proxy. Holds `(id, client, session_table_name, knowledge_table_name, ...)`. All
async methods delegate to `AgentOSClient`. Created via `RemoteDb.from_config()` by
inspecting the `ConfigResponse` domain DB lists (`remote/base.py:59-117`).

### `RemoteKnowledge` (`remote/base.py:257`)

Proxy for knowledge operations (`search_knowledge`, `upload_content`, `update_content`,
`get_content`, `delete_content_by_id`, `delete_all_content`, `get_content_status`).
All delegate to `AgentOSClient`.

---

## 7. Key Configuration Classes

### `AgnoAPISettings` (`os/settings.py`, separate from `api/settings.py`)

OS-level server settings:
```
os_security_key       — pre-shared secret for simple auth (OS_SECURITY_KEY env)
authorization_enabled — set True when JWTMiddleware is configured
docs_enabled          — whether /docs, /redoc, /openapi.json are exposed
cors_origin_list      — default allowed CORS origins
```

### `AuthorizationConfig` (`os/config.py:8`)

Pydantic model passed as `authorization_config` to `AgentOS`:
```python
class AuthorizationConfig(BaseModel):
    verification_keys: Optional[List[str]] = None
    jwks_file: Optional[str] = None
    algorithm: Optional[str] = None
    verify_audience: Optional[bool] = None
    audience: Optional[str] = None
    admin_scope: Optional[str] = None
    user_isolation: bool = False
```

---

## 8. Internal Service Token (Scheduler Auth)

When `scheduler=True`, a 32-byte URL-safe token is auto-generated (`os/app.py:317-320`):
```python
if self._scheduler_enabled and not internal_service_token:
    import secrets
    internal_service_token = secrets.token_urlsafe(32)
self._internal_service_token = internal_service_token
```

Stored on `app.state.internal_service_token` (`os/app.py` — `get_app` path). The
authentication dependency checks it with `hmac.compare_digest` (`os/auth.py:103-107`)
and grants `INTERNAL_SERVICE_SCOPES`:
```python
INTERNAL_SERVICE_SCOPES = [
    "agents:read", "agents:run",
    "teams:read", "teams:run",
    "workflows:read", "workflows:run",
    "schedules:read", "schedules:write", "schedules:delete",
]
```

---

## 9. Architecture Summary Diagram

```
User code
│
├── AgentOS(agents=[...], db=..., authorization=True, authorization_config=AuthorizationConfig(...))
│     │
│     ├── __init__: _initialize_agents/teams/workflows → _populate_registry
│     │
│     └── .get_app() → FastAPI
│           │
│           ├── Lifespan chain: db_lifespan, scheduler_lifespan, mcp_lifespan, http_client_lifespan
│           │
│           ├── Middleware stack:
│           │     CORSMiddleware
│           │     JWTMiddleware (os/middleware/jwt.py)
│           │       ↓ sets request.state.{user_id, scopes, authenticated, ...}
│           │
│           ├── Routers (all with router-level Depends(get_authentication_dependency)):
│           │     GET /config, /models
│           │     GET/POST /agents, /agents/{id}/runs (form data), SSE streaming
│           │     GET/POST /teams, /workflows (same pattern)
│           │     WS   /ws/workflows/{id}/{session_id}
│           │     CRUD /sessions, /memories, /knowledge, /traces, /eval-runs, /metrics
│           │     CRUD /schedules, /approvals, /components
│           │     GET  /registry
│           │     GET  /health, /info
│           │
│           └── (Optional) /mcp MCP server
│
├── RemoteAgent(base_url="http://...", agent_id="...", protocol="agentos")
│     └── .arun(input, stream=True, auth_token="Bearer ...")
│           └── AgentOSClient.run_agent_stream(...)
│                 └── POST /agents/{id}/runs (form, SSE)
│
└── Registry(tools=[...], dbs=[...], agents=[...])
      └── .rehydrate_function(func_dict)  ← used by Workflow DB loading
```

---

## File Reference Index

| File | Purpose |
|---|---|
| `os/app.py` | `AgentOS` class — server constructor, `get_app()`, lifespan management |
| `os/router.py` | Base, info, and WebSocket routers |
| `os/auth.py` | Security key auth, `require_resource_access`, token extraction |
| `os/config.py` | `AuthorizationConfig`, `SessionConfig`, domain config models |
| `os/scopes.py` | `AgentOSScope`, `has_required_scopes`, `get_default_scope_mappings` |
| `os/settings.py` | `AgnoAPISettings` (OS-level settings) |
| `os/schema.py` | All request/response Pydantic schemas; `RegistryContentResponse` |
| `os/middleware/jwt.py` | `JWTValidator`, `JWTMiddleware`, `TokenSource` |
| `os/middleware/user_scope.py` | `get_scoped_user_id`, `resolve_db_and_scope`, `enforce_owner_on_entity` |
| `os/middleware/trailing_slash.py` | Trailing slash normalization |
| `os/routers/agents/router.py` | Agent run endpoints, SSE streamers |
| `os/routers/registry/registry.py` | `GET /registry` endpoint |
| `os/interfaces/base.py` | `BaseInterface` abstract class |
| `os/interfaces/a2a/` | A2A server interface |
| `os/interfaces/agui/` | AG-UI streaming interface |
| `os/interfaces/slack/`, `telegram/`, `whatsapp/` | Messaging platform interfaces |
| `os/mcp.py` | MCP server creation (`get_mcp_server`) |
| `os/managers.py` | `event_buffer`, `sse_subscriber_manager` |
| `registry/registry.py` | `Registry` dataclass |
| `remote/base.py` | `BaseRemote`, `RemoteDb`, `RemoteKnowledge` |
| `agent/remote.py` | `RemoteAgent` — `arun`, `acontinue_run`, `acancel_run` |
| `client/os.py` | `AgentOSClient` — all HTTP operations |
| `client/a2a/client.py` | `A2AClient` — A2A protocol client |
| `api/api.py` | `Api` — Agno cloud telemetry client (NOT the OS API server) |
| `api/settings.py` | Agno cloud API URL settings |
