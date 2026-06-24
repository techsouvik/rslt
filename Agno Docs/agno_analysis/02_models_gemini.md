# Agno 2.6.9 — Models & Gemini Integration
**Subsystems:** `models/`, `models/google/`

---

## Table of Contents
1. [Base Model Architecture](#1-base-model-architecture)
2. [Gemini Class — All Parameters](#2-gemini-class--all-parameters)
3. [Client Initialization](#3-client-initialization)
4. [Request Parameter Construction (`get_request_params`)](#4-request-parameter-construction)
5. [Thinking / Reasoning Config](#5-thinking--reasoning-config)
6. [Google Search Grounding](#6-google-search-grounding)
7. [File Search Integration](#7-file-search-integration)
8. [Structured Output (response_model / response_schema)](#8-structured-output)
9. [Tool Calling](#9-tool-calling)
10. [Invoke / Stream Path — How Agent Calls Flow](#10-invoke--stream-path)
11. [Message Formatting (_format_messages)](#11-message-formatting)
12. [Multi-modal Support (Images, Audio, Video, Files)](#12-multi-modal-support)
13. [Response Parsing (_parse_provider_response)](#13-response-parsing)
14. [Streaming (_parse_provider_response_delta)](#14-streaming)
15. [Token Metrics](#15-token-metrics)
16. [GeminiInteractions (Alternate Backend)](#16-geminiinteractions-alternate-backend)
17. [Key Gotchas & Rules](#17-key-gotchas--rules)
18. [Provider-level File Structure Summary](#18-provider-level-file-structure-summary)

---

## 1. Base Model Architecture

**File:** `models/base.py` — `@dataclass class Model(ABC)` (line 127)

### Core Fields (base, apply to all providers)

| Field | Type | Default | Purpose |
|---|---|---|---|
| `id` | `str` | required | Model ID sent to API |
| `name` | `Optional[str]` | None | Display name (not sent to API) |
| `provider` | `Optional[str]` | None | Provider label |
| `model_type` | `ModelType` | `MODEL` | Functional role (MODEL / OUTPUT_MODEL / PARSER_MODEL) |
| `supports_native_structured_outputs` | `bool` | False | Whether provider handles structured output natively |
| `supports_json_schema_outputs` | `bool` | False | Whether provider needs raw JSON schema |
| `_tool_choice` | `Optional[Union[str, Dict]]` | None | Default tool choice mode |
| `system_prompt` | `Optional[str]` | None | Model-level system prompt override |
| `instructions` | `Optional[List[str]]` | None | Model-level instruction additions |
| `tool_message_role` | `str` | `"tool"` | Role string for tool result messages |
| `assistant_message_role` | `str` | `"assistant"` | Role string for assistant messages |
| `cache_response` | `bool` | False | Cache LLM responses to `~/.agno/cache/model_responses/` |
| `cache_ttl` | `Optional[int]` | None | Cache TTL in seconds (None = no expiry) |
| `cache_dir` | `Optional[str]` | None | Override cache directory |
| `retries` | `int` | 0 | Number of retries on `ModelProviderError` |
| `delay_between_retries` | `int` | 1 | Seconds between retries |
| `exponential_backoff` | `bool` | False | Double delay on each retry |
| `retry_with_guidance` | `bool` | True | On `RetryableModelProviderError`, retry with a guidance message appended |
| `retry_with_guidance_limit` | `int` | 1 | Max guidance-based retries |

### Abstract Methods (every provider must implement)

```python
def invoke(self, *args, **kwargs) -> ModelResponse: ...          # line 549
async def ainvoke(self, *args, **kwargs) -> ModelResponse: ...   # line 553
def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]: ...      # line 557
def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]: ...# line 561
def _parse_provider_response(self, response, **kwargs) -> ModelResponse: ... # line 565
def _parse_provider_response_delta(self, response) -> ModelResponse: ...     # line 577
```

### Top-level entry points (called by Agent)

| Method | Description |
|---|---|
| `response(messages, ...)` | Sync non-streaming; runs the full tool-call loop internally (line 647) |
| `aresponse(messages, ...)` | Async non-streaming (line 878) |
| `response_stream(messages, ...)` | Sync streaming; full tool-call loop (line 1359) |
| `aresponse_stream(messages, ...)` | Async streaming (line 1635) |

All four call `_invoke_with_retry` / `_ainvoke_with_retry` / `_invoke_stream_with_retry` / `_ainvoke_stream_with_retry` which wrap the abstract `invoke*` methods with the retry logic.

**Gemini client lifecycle note (base.py lines 865–874, 1086–1095, 1589–1598, 1866–1875):**  
The base class has Gemini-specific `finally` blocks in all four entry points. After every response/stream call, the Gemini `client` is explicitly closed and set to `None`:
- Sync: `self.client.close()`
- Async: `await self.client.aio.aclose()`

This means a new `GeminiClient` is re-created on every `invoke*` call unless you pass a pre-built client via `Gemini(client=my_client)`.

---

## 2. Gemini Class — All Parameters

**File:** `models/google/gemini.py` — `@dataclass class Gemini(Model)` (line 72)  
Default model ID: `"gemini-flash-latest"` (line 86)

### Generation / Sampling Parameters (line 117–132)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `temperature` | `Optional[float]` | None | Sampling temperature. **Drop for Gemini 2.5+ models** (use `thinking_level` instead) |
| `top_p` | `Optional[float]` | None | Nucleus sampling. **Drop for Gemini 2.5+** |
| `top_k` | `Optional[int]` | None | Top-k sampling. **Drop for Gemini 2.5+** |
| `max_output_tokens` | `Optional[int]` | None | Maximum output tokens |
| `stop_sequences` | `Optional[list[str]]` | None | Stop token sequences |
| `logprobs` | `Optional[bool]` | None | Whether to return log probabilities |
| `presence_penalty` | `Optional[float]` | None | Penalize new token presence |
| `frequency_penalty` | `Optional[float]` | None | Penalize token frequency |
| `seed` | `Optional[int]` | None | Seed for deterministic sampling |

### Response Format / Modalities (line 126–128)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `response_modalities` | `Optional[list[str]]` | None | List of `"TEXT"`, `"IMAGE"`, `"AUDIO"` |
| `speech_config` | `Optional[dict[str, Any]]` | None | TTS speech config dict |
| `cached_content` | `Optional[Any]` | None | Pre-cached content handle (Gemini prompt caching) |

### Thinking / Reasoning Parameters (line 129–131)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `thinking_budget` | `Optional[int]` | None | Token budget for thinking (Gemini 2.5 models). **Setting to 0 blocks all output** — do not use 0. |
| `include_thoughts` | `Optional[bool]` | None | Include thought summaries in response content |
| `thinking_level` | `Optional[str]` | None | `"low"` or `"high"` — high-level control for Gemini 2.5+ models (replaces temperature/top_p/top_k) |

### Search / Grounding Tools (line 97–115)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `search` | `bool` | False | Enable `GoogleSearch()` tool — Gemini 2.0+ native search grounding |
| `grounding` | `bool` | False | Enable `GoogleSearchRetrieval` — **legacy**, Gemini 1.x grounding |
| `grounding_dynamic_threshold` | `Optional[float]` | None | Dynamic threshold for legacy grounding (0.0–1.0) |
| `url_context` | `bool` | False | Enable `UrlContext()` tool — fetches URLs mentioned in prompt |
| `vertexai_search` | `bool` | False | Use Vertex AI Search (Enterprise) |
| `vertexai_search_datastore` | `Optional[str]` | None | Datastore ID for Vertex AI Search (required when `vertexai_search=True`) |
| `parallel_search` | `bool` | False | Parallel web search grounding (Vertex AI only) |
| `parallel_api_key` | `Optional[str]` | None | API key for Parallel Search (or env `PARALLEL_API_KEY`) |
| `parallel_config` | `Optional[Dict[str, Any]]` | None | Custom config for Parallel Search (e.g. `{"source_policy": {"exclude_domains": ["example.com"]}}`) |

### File Search (line 113–115)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `file_search_store_names` | `Optional[List[str]]` | None | List of File Search store names to query |
| `file_search_metadata_filter` | `Optional[str]` | None | Metadata filter expression for File Search |

### Client / Auth Parameters (line 140–149)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `api_key` | `Optional[str]` | None | Google AI API key (or env `GOOGLE_API_KEY`) |
| `vertexai` | `bool` | False | Use Vertex AI API (or env `GOOGLE_GENAI_USE_VERTEXAI=true`) |
| `project_id` | `Optional[str]` | None | GCP project (or env `GOOGLE_CLOUD_PROJECT`) |
| `location` | `Optional[str]` | None | GCP region (or env `GOOGLE_CLOUD_LOCATION`) |
| `credentials` | `Optional[Credentials]` | None | `google.oauth2.service_account.Credentials` object |
| `client_params` | `Optional[Dict[str, Any]]` | None | Additional kwargs merged into `genai.Client(...)` |
| `client` | `Optional[GeminiClient]` | None | Pre-built client (bypasses `get_client()`) |
| `timeout` | `Optional[float]` | None | HTTP timeout in seconds (converted to ms in `http_options`) |

### Other Parameters

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `function_declarations` | `Optional[List[Any]]` | None | Raw function declarations (rarely used; prefer `tools` on Agent) |
| `generation_config` | `Optional[Any]` | None | Full `GenerateContentConfig` override (merges with per-call params) |
| `safety_settings` | `Optional[List[Any]]` | None | List of `SafetySetting` objects |
| `generative_model_kwargs` | `Optional[Dict[str, Any]]` | None | Extra kwargs merged into `generation_config` dict |
| `request_params` | `Optional[Dict[str, Any]]` | None | Extra kwargs merged into `generate_content(...)` call |
| `collect_metrics_on_completion` | `bool` | True | Only collect token counts from final streaming chunk (Gemini sends cumulative counts) |
| `supports_native_structured_outputs` | `bool` | **True** | Gemini overrides base default to True |

### Role Mapping (line 152–160)

```python
role_map = {"model": "assistant"}          # Gemini → Agno
reverse_role_map = {
    "assistant": "model",                  # Agno → Gemini
    "tool": "user",                        # Tool results sent as "user" role
}
```

---

## 3. Client Initialization

**File:** `models/google/gemini.py`, `get_client()` method (line 162)

```python
def get_client(self) -> GeminiClient:
    if self.client:
        return self.client
    # ...build client_params dict...
    client_params = inject_agno_client_header(client_params)  # adds x-goog-api-client: agno/<version>
    self.client = genai.Client(**client_params)
    return self.client
```

**Vertex AI path:** sets `vertexai=True`, reads `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`.  
**Standard path:** reads `GOOGLE_API_KEY`.  
**Timeout:** converted from seconds to milliseconds and injected into `http_options.timeout`.  
**Custom headers:** `inject_agno_client_header` (in `agno/utils/gemini.py`, line 22) adds `x-goog-api-client: agno/<version>` to `http_options.headers` for Google partner tracking.

---

## 4. Request Parameter Construction

**File:** `models/google/gemini.py`, `get_request_params()` (line 277)

The method builds a single `GenerateContentConfig` object placed at `request_params["config"]`. Merge priority (later wins):

1. `self.generation_config` (if set, pre-loaded dict)
2. `self.generative_model_kwargs` (merged in)
3. Individual scalar fields (`temperature`, `top_p`, `top_k`, `max_output_tokens`, `stop_sequences`, `logprobs`, `presence_penalty`, `frequency_penalty`, `seed`, `response_modalities`, `speech_config`, `cached_content`, `safety_settings`)
4. `system_instruction` (from `system_message` arg)
5. `response_mime_type` + `response_schema` (if `response_format` provided)
6. `thinking_config` (if any thinking param set)
7. `tools` (builtin tools OR converted function declarations)
8. `tool_config` (from `tool_choice` arg)
9. `None`-values stripped before creating `GenerateContentConfig`
10. `self.request_params` merged after config (top-level `generate_content` kwargs)

The built config object is then unpacked:
```python
provider_response = self.get_client().models.generate_content(
    model=self.id,
    contents=formatted_messages,
    **request_kwargs,          # {"config": GenerateContentConfig(...)}
)
```

---

## 5. Thinking / Reasoning Config

**File:** `models/google/gemini.py`, lines 328–336

```python
thinking_config_params: Dict[str, Any] = {}
if self.thinking_budget is not None:
    thinking_config_params["thinking_budget"] = self.thinking_budget
if self.include_thoughts is not None:
    thinking_config_params["include_thoughts"] = self.include_thoughts
if self.thinking_level is not None:
    thinking_config_params["thinking_level"] = self.thinking_level
if thinking_config_params:
    config["thinking_config"] = ThinkingConfig(**thinking_config_params)
```

### Rules

| Rule | Detail |
|---|---|
| `thinking_budget=0` **blocks all output** | Do NOT set `thinking_budget=0`. It disables thinking but also causes the model to emit no text. |
| Gemini 2.5+ models | Use `thinking_level="low"` or `thinking_level="high"`. Drop `temperature`, `top_p`, `top_k` (they are ignored or error). |
| Gemini 2.0 / 1.x models | Use `temperature`, `top_p`, `top_k` normally. `thinking_level` is not applicable. |
| `include_thoughts=True` | Thought text appears in `reasoning_content` field of `ModelResponse` (not in `content`). Captured via `part.thought == True` in response parsing. |

---

## 6. Google Search Grounding

**File:** `models/google/gemini.py`, lines 341–395

### Two Search Patterns

**Pattern A — Modern (Gemini 2.0+): `search=True`**
```python
# Adds Tool(google_search=GoogleSearch()) to config["tools"]
Gemini(id="gemini-2.0-flash", search=True)
```
Calls `Tool(google_search=GoogleSearch())` — no dynamic threshold, clean grounding for current models.

**Pattern B — Legacy (Gemini 1.x): `grounding=True`**
```python
# Adds Tool(google_search=GoogleSearchRetrieval(dynamic_retrieval_config=DynamicRetrievalConfig(...)))
Gemini(id="gemini-1.5-pro", grounding=True, grounding_dynamic_threshold=0.3)
```
Log warning is emitted: `"This is a legacy tool. For Gemini 2.0+ Please use enable search flag instead."`

**Pattern C — URL Context: `url_context=True`**
```python
# Adds Tool(url_context=UrlContext())
Gemini(id="gemini-2.0-flash", url_context=True)
```
Fetches and reads URLs that appear in the conversation.

**Pattern D — Vertex AI Search: `vertexai_search=True`**
```python
Gemini(vertexai=True, vertexai_search=True, vertexai_search_datastore="projects/.../dataStores/...")
```

**Pattern E — Parallel AI Search (Vertex AI only): `parallel_search=True`**
```python
Gemini(vertexai=True, parallel_search=True, parallel_api_key="...")
```
Requires `vertexai=True`; cannot be combined with `search=True` or `grounding=True`.

### Mutual Exclusion Rule
**When any builtin tool is enabled (search, grounding, url_context, vertexai_search, file_search, parallel_search), external agent tools (function declarations) are disabled** (line 398–401):
```python
if builtin_tools:
    if tools:
        log_info("Built-in tools enabled. External tools will be disabled.")
    config["tools"] = builtin_tools
elif tools:
    config["tools"] = [format_function_definitions(tools)]
```

### Citation / Grounding Metadata
Grounding results surface via `response.candidates[0].grounding_metadata` → parsed into `ModelResponse.citations`:
- `citations.urls` — list of `UrlCitation(url, title)`
- `citations.search_queries` — list of web search queries issued
- `citations.raw["grounding_metadata"]` — full raw dict

URL context results surface via `response.candidates[0].url_context_metadata` → also merged into `citations.urls`.

---

## 7. File Search Integration

**File:** `models/google/gemini.py`, lines 262–275, 1515–2079

### Enabling File Search in Requests
```python
Gemini(
    id="gemini-2.5-flash",
    file_search_store_names=["fileSearchStores/my-store-abc"],
    file_search_metadata_filter="author = 'Alice'"  # optional
)
```

This calls `_append_file_search_tool()` (line 262):
```python
builtin_tools.append(Tool(file_search=FileSearch(**file_search_config)))
```

Same mutual exclusion applies as other builtin tools — external function tools are disabled.

### File Search Store Management (methods on Gemini class)

| Method | Description |
|---|---|
| `create_file_search_store(display_name, embedding_model)` | Create a new store. Use `"models/gemini-embedding-2"` for multimodal/image search. |
| `async_create_file_search_store(...)` | Async version |
| `list_file_search_stores(page_size=100)` | List all stores |
| `get_file_search_store(name)` | Get a store by name |
| `delete_file_search_store(name, force=False)` | Delete a store |
| `upload_to_file_search_store(file_path, store_name, ...)` | Upload a file directly; returns `Operation` (long-running) |
| `import_file_to_store(file_name, store_name, ...)` | Import existing Files API file into a store |
| `list_documents(store_name, page_size=20)` | List documents in a store |
| `get_document(document_name)` | Get a specific document |
| `delete_document(document_name)` | Delete a document |
| `download_blob(media_id)` | Download a cited image blob from multimodal search results |
| `wait_for_operation(operation, poll_interval=5, max_wait=600)` | Poll a long-running operation until done |

**Chunking config example:**
```python
chunking_config = {
    "white_space_config": {
        "max_tokens_per_chunk": 200,
        "max_overlap_tokens": 20
    }
}
```

**Custom metadata example:**
```python
custom_metadata = [
    {"key": "author", "string_value": "John Doe"},
    {"key": "year", "numeric_value": 2024}
]
```

---

## 8. Structured Output

**File:** `models/google/gemini.py` lines 321–325; `agno/utils/gemini.py` lines 50–454

### How it works

When `response_format=MyPydanticModel` is passed to `invoke()`:
1. `get_request_params()` sets `config["response_mime_type"] = "application/json"`
2. Calls `prepare_response_schema(MyPydanticModel)` — returns either the Pydantic class directly or a converted `Schema` object
3. Result set as `config["response_schema"]`

`prepare_response_schema()` first checks `needs_conversion()`:
- If schema has `additionalProperties` (Dict fields) → convert to `Schema`
- If schema has circular `$ref` self-references → convert to `Schema`
- Otherwise → pass the Pydantic class directly (Gemini handles it natively)

`convert_schema()` does a full recursive JSON Schema → `google.genai.types.Schema` conversion with:
- Cycle detection (`visited_refs` set)
- `additionalProperties` → placeholder `example_key` property workaround (Gemini rejects `additionalProperties` directly)
- Null/Optional handling → `Schema.nullable = True`
- `anyOf` unwrapping

### Gotcha: Dict fields
`Dict[str, T]` fields in Pydantic models trigger conversion. The schema conversion creates a placeholder property `example_key` with a description explaining the actual structure. The model can still produce arbitrary keys, but the schema representation is synthetic.

### `supports_native_structured_outputs = True` (line 90)
The Gemini class sets this to `True`, signaling to Agno's agent that native structured output is available (no prompt-engineering fallback needed).

---

## 9. Tool Calling

**File:** `models/google/gemini.py`, `get_request_params()` lines 397–415; `agno/utils/gemini.py` `format_function_definitions()` line 432

### Function Declaration Conversion
```python
# agno/utils/gemini.py line 432
def format_function_definitions(tools_list: List[Dict[str, Any]]) -> Optional[Tool]:
    # Converts list of {"type": "function", "function": {...}} dicts
    # → Tool(function_declarations=[FunctionDeclaration(...), ...])
```
Parameters are converted recursively via `convert_schema()`.

### Tool Choice Modes (line 405–415)
```python
"auto"      → FunctionCallingConfigMode.AUTO
"none"      → FunctionCallingConfigMode.NONE
"validated" → FunctionCallingConfigMode.VALIDATED
"any"       → FunctionCallingConfigMode.ANY
```

### MALFORMED_FUNCTION_CALL Recovery
If a streaming/non-streaming response has `finish_reason == MALFORMED_FUNCTION_CALL`, the model raises `RetryableModelProviderError` with guidance message (file `models/google/utils.py` line 132):
```
The previous function call was malformed. Please try again...
- Generate the function call JSON directly, do not generate code
- Use the function name exactly as defined (no namespace prefixes like 'default_api.')
```
The base class `_invoke_with_retry` / `_ainvoke_with_retry` catches `RetryableModelProviderError` and retries with the guidance appended as a temporary user message.

### Tool Results Format
Gemini requires tool results as `"user"` role messages (see `reverse_role_map`). `format_function_call_results()` (line 1108) simply extends `messages` with the individual result `Message` objects — each has `role="tool"`, `tool_call_id`, `tool_name`, and `content`. The `_format_messages()` method then converts them to `Part.from_function_response(name=..., response={"result": ...})`.

---

## 10. Invoke / Stream Path

### Sync Non-Streaming (`response()` → `invoke()`)
```
Agent.run()
  └→ Model.response(messages, response_format, tools, ...)  [base.py:647]
       └→ _process_model_response(...)                      [base.py:1099]
            └→ _invoke_with_retry(...)                      [base.py:228]
                 └→ Gemini.invoke(messages, ...)            [gemini.py:537]
                      ├→ _format_messages(messages)
                      ├→ get_request_params(...)
                      └→ client.models.generate_content(model, contents, config=...)
                           └→ _parse_provider_response(response)
```

### Sync Streaming (`response_stream()` → `invoke_stream()`)
```
Agent.run(stream=True)
  └→ Model.response_stream(messages, ...)               [base.py:1359]
       └→ process_response_stream(...)                  [base.py:1323]
            └→ _invoke_stream_with_retry(...)
                 └→ Gemini.invoke_stream(messages, ...) [gemini.py:595]
                      └→ client.models.generate_content_stream(...)
                           └→ for chunk: _parse_provider_response_delta(chunk)
```

### Async variants use `aio.models.generate_content` / `aio.models.generate_content_stream`.

### Tool Call Loop
The `response()` / `response_stream()` methods contain a `while True` loop. After receiving a response with `tool_calls`, they:
1. Execute the function calls (via `run_function_calls`)
2. Add results to messages
3. Loop back to invoke the model again
4. Break when no tool calls returned OR stop conditions are met

---

## 11. Message Formatting

**File:** `models/google/gemini.py`, `_format_messages()` (line 768)

### Role Handling
- `"system"` / `"developer"` messages → extracted as `system_message` string (not in `contents`)
- `"assistant"` → mapped to `"model"` 
- `"tool"` → mapped to `"user"` (tool results become user-role content)

### Content Conversion
- Text → `Part.from_text(text=...)`
- Tool call (model turn) → `Part.from_function_call(name=..., args=...)`
- Tool result → `Part.from_function_response(name=..., response={"result": ...})`
- Image (URL/bytes) → `Part.from_bytes(mime_type=..., data=...)` via `format_image_for_message()`
- Image (GeminiFile) → passed directly as `image.content`
- Video (GeminiFile/URI) → `Part.from_uri(file_uri=..., mime_type=...)`
- Video (bytes) → `Part.from_bytes(...)`
- Video (local path) → uploaded via `client.files.upload(...)`, polled until ACTIVE
- Audio (bytes/URL) → `Part.from_bytes(...)`
- Audio (local path) → uploaded via `client.files.upload(...)`, polled until ACTIVE
- Files (<20MB local) → `Part.from_bytes(...)`
- Files (≥20MB local) → uploaded via `client.files.upload(...)`
- Files (GCS `gs://`) → `Part.from_uri(...)` direct
- Files (HTTPS with known mime_type) → `Part.from_uri(...)` direct
- Files (`GeminiFile` external) → `Part.from_uri(...)`

**Thought signatures** (line 804–821): For models with thinking enabled, `part.thought_signature` (a bytes blob) is stored in `message.provider_data["thought_signature"]` (base64-encoded) and re-attached to the `Part` when that message is sent back. This enables multi-turn consistency of thinking context.

**Consecutive same-role merge** (lines 907–913): Gemini rejects consecutive messages with the same role. After building all `Content` objects, they are merged:
```python
for msg in formatted_messages:
    if merged and merged[-1].role == msg.role:
        merged[-1].parts.extend(msg.parts)
    else:
        merged.append(msg)
```

**`normalize_tool_messages`** (line 779): Called first — expands any legacy combined tool messages into individual canonical messages for compatibility.

---

## 12. Multi-modal Support

### Images
- Pass `Image(url="...")`, `Image(filepath="...")`, or `Image(content=bytes_data)` in `Message.images`
- Or pre-upload via `client.files.upload(...)` → pass `Image(content=GeminiFile_object)`
- MIME types resolved by `get_mime_type()` with fallback mapping in `models/google/utils.py`

### Audio
- `Audio(content=bytes)` → `Part.from_bytes(mime_type=..., data=...)`
- `Audio(url="...")` → downloads, then `Part.from_bytes`
- `Audio(filepath="...")` → uploaded via `client.files.upload(...)`, polled until state=SUCCESS
- Supported MIME types: `audio/mp3`, `audio/wav`, `audio/ogg`, `audio/flac`, `audio/aac`

### Video
- `Video(content=GeminiFile)` → `Part.from_uri(file_uri=video.content.uri, mime_type=...)`
- `Video(filepath="...")` → uploaded, polled for processing
- `Video(url="...")` → `Part.from_uri(file_uri=video.url, mime_type=...)`
- `Video(content=bytes)` → `Part.from_bytes(...)`

### Files (PDFs, etc.)
- Local <20MB → inline `Part.from_bytes`
- Local ≥20MB → `client.files.upload(...)` 
- GCS `gs://` → direct `Part.from_uri`
- HTTPS with known `mime_type` → direct `Part.from_uri` (supports up to 100MB Gemini server-side)
- `GeminiFile` object → `Part.from_uri`

### TTS / Audio Output
- Set `response_modalities=["AUDIO"]` and `speech_config={...}`
- Response audio appears in `ModelResponse.audio` as `Audio(content=bytes, mime_type="audio/...")`
- Parsed from `part.inline_data` where `mime_type.startswith("audio/")`

### Image Output (Imagen / multimodal)
- Response images appear in `ModelResponse.images` as `Image(content=bytes, mime_type="image/...")`
- Parsed from `part.inline_data` where `mime_type` does NOT start with `"audio/"`

---

## 13. Response Parsing

**File:** `models/google/gemini.py`, `_parse_provider_response()` (line 1124)

```
response.candidates[0].content.parts
  ├── part.text + part.thought=False → model_response.content
  ├── part.text + part.thought=True  → model_response.reasoning_content
  ├── part.thought_signature          → model_response.provider_data["thought_signature"] (base64)
  ├── part.inline_data (audio/)      → model_response.audio = Audio(...)
  ├── part.inline_data (other)       → model_response.images.append(Image(...))
  └── part.function_call             → model_response.tool_calls.append({id, type, function:{name, arguments}})

response.candidates[0].grounding_metadata → model_response.citations.urls, .search_queries, .raw
response.candidates[0].url_context_metadata → merged into model_response.citations.urls
response.usage_metadata → model_response.response_usage (via _get_metrics)
```

**Finish reason check:** If `finish_reason == MALFORMED_FUNCTION_CALL` and `self.retry_with_guidance=True`, raises `RetryableModelProviderError`.

**Empty content guard** (line 1293): If role is set but content is None and no tool_calls, sets `content = ""` to avoid downstream None errors.

---

## 14. Streaming

**File:** `models/google/gemini.py`, `_parse_provider_response_delta()` (line 1298)

Identical structure to `_parse_provider_response()` but called per chunk.

**Metrics collection:** Controlled by `_should_collect_metrics()` (line 1478):
```python
def _should_collect_metrics(self, response, candidate) -> bool:
    if not hasattr(response, "usage_metadata") or response.usage_metadata is None:
        return False
    if not self.collect_metrics_on_completion:
        return True
    # Default: only collect when candidate.finish_reason is not None (final chunk)
    return hasattr(candidate, "finish_reason") and candidate.finish_reason is not None
```
`collect_metrics_on_completion=True` (default) means token counts are only read from the final chunk because Gemini sends cumulative totals in every chunk.

**Streaming delta accumulation** in base class `_populate_stream_data()` (base.py:1913):
- Content deltas → appended to `stream_data.response_content`
- Reasoning deltas → appended to `stream_data.response_reasoning_content`
- Tool calls → extended in `stream_data.response_tool_calls`
- Citations → replaced (last wins)
- Metrics → accumulated via `MessageMetrics +=`

---

## 15. Token Metrics

**File:** `models/google/gemini.py`, `_get_metrics()` (line 1490)

```python
metrics.input_tokens  = response_usage.prompt_token_count
metrics.output_tokens = response_usage.candidates_token_count
metrics.reasoning_tokens = response_usage.thoughts_token_count  # if present
metrics.total_tokens  = input_tokens + output_tokens
metrics.cache_read_tokens = response_usage.cached_content_token_count
metrics.provider_metrics = {"traffic_type": response_usage.traffic_type}  # if present
```

Note: `cache_write_tokens` is NOT populated (Gemini does not report cache write counts in `usage_metadata`).

### Token Counting
`count_tokens()` / `acount_tokens()` (lines 430–535):
- **Vertex AI:** Full API counting with `system_instruction` + `tools` in config
- **Google AI Studio:** API counts content tokens only; system + tools estimated locally via `count_text_tokens()` / `count_tool_tokens()` (hybrid approach, because Google AI Studio API doesn't accept system/tool in count_tokens call)

---

## 16. GeminiInteractions (Alternate Backend)

**File:** `models/google/gemini_interactions.py`

A second model class for Google's **Interactions API** — a higher-level API for multi-turn conversations with server-side state and typed execution steps.

### Key difference from `Gemini`
The Interactions API manages conversation history server-side and returns typed `Step` objects rather than raw `Content`:

```python
# Step types available:
ThoughtStep, ModelOutputStep,
FunctionCallStep, FunctionResultStep,
CodeExecutionCallStep, CodeExecutionResultStep,
URLContextCallStep, URLContextResultStep,
MCPServerToolCallStep, MCPServerToolResultStep,
GoogleSearchCallStep, GoogleSearchResultStep,
FileSearchCallStep, FileSearchResultStep,
GoogleMapsCallStep, GoogleMapsResultStep
```

### Stream delta types
```python
DeltaText, DeltaImage, DeltaThoughtSummary, DeltaThoughtSignature,
DeltaArgumentsDelta,  # for function call arg streaming
DeltaCodeExecutionCall, DeltaFileSearchCall, DeltaGoogleMapsCall,
DeltaGoogleSearchCall, DeltaMCPServerToolCall, DeltaURLContextCall,
DeltaCodeExecutionResult, DeltaFileSearchResult, DeltaFunctionResult,
DeltaGoogleMapsResult, DeltaGoogleSearchResult, DeltaMCPServerToolResult,
DeltaURLContextResult
```

### When to use
- Server-side tool execution (Code Execution, Google Search, Maps) that Gemini handles natively
- You want rich audit trail of step types in `ModelResponse.tool_executions`
- Multi-turn without re-sending full history each time

---

## 17. Key Gotchas & Rules

### 1. `thinking_budget=0` blocks output
Never set `thinking_budget=0`. It effectively disables all model output. Either omit it or set a positive value (e.g., 1024).

### 2. Gemini 2.5+ model params
Drop `temperature`, `top_p`, `top_k` for `gemini-2.5-*` models. Use `thinking_level="low"` or `thinking_level="high"`. Setting legacy params may cause API errors or be silently ignored.

### 3. Builtin tools disable external tools
When `search=True`, `grounding=True`, `url_context=True`, `vertexai_search=True`, `file_search_store_names=[...]`, or `parallel_search=True` is set, **external function tools are entirely disabled**. You cannot mix builtin and custom tools. A warning is logged.

### 4. `grounding=True` is legacy
For Gemini 2.0+, use `search=True`. `grounding=True` uses the older `GoogleSearchRetrieval` path and emits a warning.

### 5. Client is closed and nulled after every call
The base class closes the Gemini client in `finally` blocks of all four entry points. If you need connection reuse, pass a pre-built `client=` to the `Gemini(...)` constructor.

### 6. Consecutive same-role message merge
Gemini API rejects consecutive messages with the same role. Agno auto-merges them in `_format_messages()`. No action needed from calling code, but be aware that multiple user messages in a row (e.g., from multi-tool results) will be merged.

### 7. Dict fields in Pydantic schemas
`Dict[str, T]` fields trigger schema conversion via `convert_schema()`. The resulting Gemini schema uses a synthetic `example_key` placeholder property. The model can still produce arbitrary keys, but the schema sent to the API is not a faithful representation.

### 8. Tool results sent as "user" role
Gemini uses `"user"` role for function responses. `reverse_role_map["tool"] = "user"` and `Part.from_function_response(...)` is used. This is transparent to calling code.

### 9. Thought signatures required for multi-turn thinking
If using `thinking_budget > 0` across multiple turns, the `thought_signature` must be re-attached to each Part that had thinking. Agno handles this via `message.provider_data["thought_signature"]` — as long as you don't strip `provider_data` from messages, multi-turn thinking works correctly.

### 10. Streaming metrics are cumulative
Gemini sends cumulative token counts in every streaming chunk. `collect_metrics_on_completion=True` (default) reads counts only from the final chunk (when `finish_reason` is set). Override with `collect_metrics_on_completion=False` to collect from every chunk (will over-count).

### 11. `parallel_search` requires Vertex AI
`parallel_search=True` requires `vertexai=True` and cannot be combined with `search=True` or `grounding=True`.

### 12. File uploads are cached by stem name
When uploading audio/video/large files, Agno uses `files/{path.stem.lower().replace('_', '')}` as the remote name and checks for an existing upload before re-uploading. If a file with the same stem is already uploaded and in SUCCESS state, it reuses it.

---

## 18. Provider-level File Structure Summary

```
models/
├── base.py                    — Abstract Model class, tool-call loop, retry logic, cache
├── message.py                 — Message, Citations, UrlCitation dataclasses
├── response.py                — ModelResponse, ModelResponseEvent, ToolExecution
├── metrics.py                 — MessageMetrics accumulation helpers
├── defaults.py                — Default model config
├── fallback.py                — FallbackModel wrapper
└── google/
    ├── __init__.py            — exports: Gemini, GeminiInteractions
    ├── gemini.py              — Primary Gemini class (77 symbols, ~2079 lines)
    ├── gemini_interactions.py — Interactions API variant (66 symbols)
    └── utils.py               — MIME map, GeminiFinishReason, MALFORMED_FUNCTION_CALL_GUIDANCE,
                                  media_to_content_item, get_mime_type
agno/utils/gemini.py           — inject_agno_client_header, prepare_response_schema,
                                  needs_conversion, has_additional_properties,
                                  convert_schema, format_function_definitions,
                                  format_image_for_message
```

### Imports required for Gemini
```python
from google.genai.types import (
    Content, DynamicRetrievalConfig, FileSearch, FunctionCallingConfigMode,
    GenerateContentConfig, GenerateContentResponse,
    GenerateContentResponseUsageMetadata, GoogleSearch, GoogleSearchRetrieval,
    GroundingMetadata, Operation, Part, Retrieval, ThinkingConfig, Tool,
    UrlContext, VertexAISearch, File as GeminiFile,
)
from google.oauth2.service_account import Credentials
# Optional (may not exist in older SDK versions):
from google.genai.types import ToolParallelAiSearch  # try/except ImportError
```

---

*Generated 2026-06-04 from Agno 2.6.9 source at `C:/Users/USER/Desktop/LBM Memry/venv/Lib/site-packages/agno`.*
