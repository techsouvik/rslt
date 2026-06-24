# Agno 2.6.9 — Knowledge, Memory & VectorDB
**Subsystems:** knowledge/, memory/, vectordb/, session/

---

## Table of Contents

1. [Knowledge Subsystem](#1-knowledge-subsystem)
   - 1.1 Core Class: `Knowledge`
   - 1.2 Knowledge Sources / Readers
   - 1.3 Chunking Strategies
   - 1.4 Embedders
   - 1.5 Retrieval Path (how knowledge is searched at run-time)
   - 1.6 `search_knowledge_base` Tool Integration
   - 1.7 Remote Loaders
   - 1.8 Rerankers
2. [Memory Subsystem](#2-memory-subsystem)
   - 2.1 `MemoryManager` class
   - 2.2 `UserMemory` schema
   - 2.3 Memory injection into system prompt
   - 2.4 Memory creation (background task)
   - 2.5 Memory DB storage backends
   - 2.6 Memory summarization / optimization
   - 2.7 `create_session_summary`
3. [VectorDB Subsystem](#3-vectordb-subsystem)
   - 3.1 `VectorDb` base interface
   - 3.2 Complete backend listing
   - 3.3 Distance metrics & score normalization
   - 3.4 Search types
   - 3.5 PgVector (annotated concrete backend)
   - 3.6 Qdrant (annotated concrete backend)
   - 3.7 Embedding flow: Document → embed → upsert
4. [Session Subsystem](#4-session-subsystem)
   - 4.1 `AgentSession` dataclass
   - 4.2 `session_data` blob — what lives inside it
   - 4.3 Session storage (BaseDb)
   - 4.4 Session lifecycle in the agent
   - 4.5 `session_state` access utilities
5. [Cross-Cutting: How Everything Wires Together](#5-cross-cutting-how-everything-wires-together)

---

## 1. Knowledge Subsystem

### 1.1 Core Class: `Knowledge`

**File:** `knowledge/knowledge.py:42`

```python
@dataclass
class Knowledge(RemoteKnowledge):
    name: Optional[str] = None
    description: Optional[str] = None
    vector_db: Optional[Any] = None               # VectorDb instance
    contents_db: Optional[Union[BaseDb, AsyncBaseDb]] = None  # metadata store
    max_results: int = 10
    readers: Optional[Dict[str, Reader]] = None
    content_sources: Optional[List[BaseStorageConfig]] = None
    isolate_vector_search: bool = False            # multi-KB sharing guard
```

- `Knowledge` extends `RemoteKnowledge` (`knowledge/remote_knowledge.py`). `RemoteKnowledge` holds the AgentOS-hosted variant; `Knowledge` is the local/self-hosted class.
- `__post_init__` (`knowledge/knowledge.py:58`) calls `self.vector_db.create()` if the collection does not yet exist, then calls `self.construct_readers()` to initialize the lazy `readers` dict.
- `isolate_vector_search = True` injects a `{"linked_to": self.name}` metadata filter on every `search()` / `asearch()` call, enabling multiple `Knowledge` instances that share the same VectorDB collection (`knowledge/knowledge.py:533–540`).

**Key public API:**

| Method | Line | Notes |
|--------|------|-------|
| `insert(path/url/text_content/...)` | 91 | Sync. Dispatches to `_load_content`. |
| `ainsert(...)` | 177 | Async counterpart. |
| `insert_many(contents/paths/urls/...)` | 375 | Batch sync. Iterates and calls `insert`. |
| `ainsert_many(...)` | 247 | Batch async. |
| `search(query, max_results, filters, search_type)` | 508 | Returns `List[Document]`. Delegates to `vector_db.search()`. |
| `asearch(query, ...)` | 549 | Async; tries `vector_db.async_search()`, falls back to sync on `NotImplementedError`. |
| `get_content(limit, page, ...)` | 597 | Reads metadata from `contents_db`. |
| `validate_filters(filters)` | 802 | Cross-checks filter keys against stored metadata keys. |
| `remove_content_by_id(content_id)` | ~695 | Deletes from both vector_db and contents_db. |

**Content loading internals** (`knowledge/knowledge.py:1089–1134`):

`_load_content` dispatches based on what is set on the `Content` object:
- `content.path` → `_load_from_path` (handles dir traversal, file extension detection)
- `content.url` → `_load_from_url` (HTTP fetch via `async_fetch_with_retry`)
- `content.file_data` → `_load_from_content` (raw bytes / text)
- `content.topics` → `_load_from_topics` (Wikipedia-style topic look-up)
- `content.remote_content` → `_load_from_remote_content` (S3/GCS/GitHub/SharePoint)

Reader selection (`knowledge/knowledge.py:957–1083`):
- `_select_reader_by_extension(ext)` maps `.pdf→pdf_reader`, `.csv→csv_reader`, `.docx→docx_reader`, `.pptx→pptx_reader`, `.json→json_reader`, `.markdown→markdown_reader`, `.xlsx/.xls→excel_reader`, else `text_reader`.
- All reader properties are lazily loaded via `_get_reader(type)` which calls `ReaderFactory.create_reader(type)`.

Content hash deduplication (`knowledge/knowledge.py:153`):
```python
content.content_hash = self._build_content_hash(content)
content.id = generate_id(content.content_hash)
```
`_should_skip` (`knowledge/knowledge.py:1136`) calls `vector_db.content_hash_exists(hash)` — if True and `skip_if_exists=True`, the document is skipped without re-embedding.

---

### 1.2 Knowledge Sources / Readers

All readers live under `knowledge/reader/`. They extend `Reader` (`knowledge/reader/base.py`).

**Complete reader list** (from `knowledge/reader/__init__.py` and directory listing):

| Reader class | File | Format |
|---|---|---|
| `PDFReader` / `PDFUrlReader` | `pdf_reader.py` | PDF (uses PyMuPDF / pdfplumber) |
| `CSVReader` | `csv_reader.py` | CSV |
| `FieldLabeledCSVReader` | `field_labeled_csv_reader.py` | CSV with field labels |
| `DocxReader` | `docx_reader.py` | .docx (Word) |
| `ExcelReader` | `excel_reader.py` | .xlsx / .xls |
| `PPTXReader` | `pptx_reader.py` | PowerPoint |
| `JSONReader` | `json_reader.py` | JSON |
| `MarkdownReader` | `markdown_reader.py` | Markdown |
| `TextReader` | `text_reader.py` | Plain text |
| `WebsiteReader` | `website_reader.py` | HTTP/HTML crawl |
| `FirecrawlReader` | `firecrawl_reader.py` | Firecrawl API |
| `TavilyReader` | `tavily_reader.py` | Tavily search API |
| `WebSearchReader` | `web_search_reader.py` | Generic web search |
| `ArxivReader` | `arxiv_reader.py` | arXiv papers |
| `WikipediaReader` | `wikipedia_reader.py` | Wikipedia |
| `YouTubeReader` | `youtube_reader.py` | YouTube transcripts |
| `LLMsTxtReader` | `llms_txt_reader.py` | llms.txt standard |
| `DoclingReader` | `docling_reader.py` | Docling multi-format |
| `S3Reader` | `s3_reader.py` | AWS S3 |

`ReaderFactory` (`knowledge/reader/reader_factory.py`) maps string IDs (`"pdf"`, `"csv"`, etc.) to reader classes and handles lazy import.

Every `Reader` exposes:
```python
def read(self, source: Union[Path, str, BytesIO], name=None) -> List[Document]: ...
async def async_read(self, source, name=None) -> List[Document]: ...
```
(`knowledge/reader/base.py`)

---

### 1.3 Chunking Strategies

**File:** `knowledge/chunking/strategy.py`

Abstract base:
```python
class ChunkingStrategy(ABC):
    @abstractmethod
    def chunk(self, document: Document) -> List[Document]: ...
    async def achunk(self, document: Document) -> List[Document]: ...   # default: calls sync chunk
    def clean_text(self, text: str) -> str: ...                         # collapses whitespace
    def _generate_chunk_id(self, doc, chunk_number, content, prefix) -> Optional[str]: ...
```

**All strategies** (`ChunkingStrategyType` enum, `strategy.py:58`):

| Enum value | Class | File | chunk_size | overlap | Algorithm |
|---|---|---|---|---|---|
| `DocumentChunker` | `DocumentChunking` | `document.py:7` | 5000 | 0 | Split on `\n\n` paragraphs; recursively splits on sentences for oversized paragraphs |
| `FixedSizeChunker` | `FixedSizeChunking` | `fixed.py:7` | 5000 | 0 | Character-level fixed window; avoids mid-word splits |
| `RecursiveChunker` | `RecursiveChunking` | `recursive.py:8` | 5000 | 0 | Slide forward, seek `\n` or `.` as break-point; advances by `chunk_size - overlap` |
| `MarkdownChunker` | `MarkdownChunking` | `markdown.py:~29` | 5000 | 0 | Uses `unstructured.partition_md` + `chunk_by_title`; falls back to `\n\n` split; optional `split_on_headings` (bool or heading level int) |
| `SemanticChunker` | `SemanticChunking` | `semantic.py` | configurable | N/A | Semantic similarity grouping (no overlap support) |
| `AgenticChunker` | `AgenticChunking` | `agentic.py` | max_chunk_size | N/A | LLM-driven chunking (uses `max_chunk_size` not `chunk_size`) |
| `CodeChunker` | `CodeChunking` | `code.py` | configurable | N/A | Code-aware splitting (no overlap) |
| `RowChunker` | `RowChunking` | `row.py` | N/A | N/A | Row-per-document (CSV/table data); `skip_header`, `clean_rows` options |

**Overlap behaviour** (DocumentChunking, FixedSizeChunking, RecursiveChunking, MarkdownChunking):
- `overlap > 0`: After building non-overlapping chunk list, post-processes to prepend `prev_chunk.content[-overlap:]` to each chunk.
- `RecursiveChunking`: Overlap is built in-line: `new_start = end - self.overlap`. Requires `overlap < chunk_size`; warns if `overlap > chunk_size * 0.15`.

**Factory** (`ChunkingStrategyFactory.create_strategy`, `strategy.py:86`):
Called by `process_content` (server route) via `set_chunking_strategy_from_string`. Accepts `chunk_size` and `overlap` kwargs and maps them to each strategy's actual init parameter names.

---

### 1.4 Embedders

All embedders extend `Embedder` (`knowledge/embedder/base.py:6`):
```python
@dataclass
class Embedder:
    dimensions: Optional[int] = 1536
    enable_batch: bool = False
    batch_size: int = 100

    def get_embedding(self, text: str) -> List[float]: ...
    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]: ...
    async def async_get_embedding(self, text: str) -> List[float]: ...
    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]: ...
```

**Complete embedder list** (`knowledge/embedder/`):

| Class | File | Provider |
|---|---|---|
| `OpenAIEmbedder` | `openai.py` | OpenAI (default `text-embedding-3-small`) |
| `AzureOpenAIEmbedder` | `azure_openai.py` | Azure OpenAI |
| `CohereEmbedder` | `cohere.py` | Cohere |
| `GoogleEmbedder` | `google.py` | Google (Gemini embeddings) |
| `JinaEmbedder` | `jina.py` | Jina AI (jina-embeddings-v3 etc.) |
| `MistralEmbedder` | `mistral.py` | Mistral AI |
| `OllamaEmbedder` | `ollama.py` | Ollama (local) |
| `HuggingFaceEmbedder` | `huggingface.py` | HuggingFace transformers |
| `SentenceTransformerEmbedder` | `sentence_transformer.py` | sentence-transformers |
| `FastEmbedEmbedder` | `fastembed.py` | FastEmbed |
| `VoyageAIEmbedder` | `voyageai.py` | Voyage AI |
| `FireworksEmbedder` | `fireworks.py` | Fireworks AI |
| `TogetherEmbedder` | `together.py` | Together AI |
| `NebIusEmbedder` | `nebius.py` | Nebius |
| `VllmEmbedder` | `vllm.py` | vLLM local inference |
| `OpenAILikeEmbedder` | `openai_like.py` | Any OpenAI-compatible endpoint |
| `LangDBEmbedder` | `langdb.py` | LangDB |
| `AWSBedrockEmbedder` | `aws_bedrock.py` | AWS Bedrock |

**Embedding call flow:**
```
Knowledge.insert(...)
  → _load_content(...)
    → reader.read(source) → List[Document]
    → apply chunking_strategy.chunk(doc) → List[Document]
    → _prepare_documents_for_insert(docs, content_id, ...)
    → vector_db.upsert(content_hash, docs)
      → for doc in docs: doc.embed(embedder=self.embedder)
         → embedder.get_embedding_and_usage(doc.content)
         → doc.embedding = List[float]
```
(`knowledge/knowledge.py:1285–1340`, `knowledge/document/base.py:23–37`, `vectordb/milvus/milvus.py:555`)

---

### 1.5 Retrieval Path (how knowledge is searched at run-time)

At run time the retrieval path is:

```
Agent.run(message)
  → get_system_message(agent, session, run_context)  [_messages.py:106]
      → (if search_knowledge=False and add_knowledge_to_context=True):
            _get_resolved_knowledge(agent, run_context)
            knowledge.search(query=message, max_results=...)   [EAGER inject into system prompt]
      → (if search_knowledge=True):
            adds search_knowledge_base tool to tool list
            → agent adds: <search_instructions> to system_message
  → model.response(messages)
    → model calls search_knowledge_base(query)  [_default_tools.py:224]
       → _messages.get_relevant_docs_from_knowledge(agent, query, filters, ...)
           → knowledge.search(query, max_results, filters)      [knowledge.py:508]
               → vector_db.search(query, limit, filters)
                   → embedder.get_embedding(query) → query_vector
                   → vector store ANN search
                   → return List[Document]
           → convert docs to dict / string
       → return formatted str to model
```

**Key flag:** `agent.search_knowledge: bool` (default `True`) — when True, knowledge is searched on-demand via a tool call. When False, documents are eagerly injected in the system prompt.

**Filter path** (`_default_tools.py:141–152`):
- If `enable_agentic_filters=True`, the model can pass `List[KnowledgeFilter]` to the tool; these are merged with the user-provided `knowledge_filters` via `get_agentic_or_user_search_filters`.

---

### 1.6 `search_knowledge_base` Tool Integration

**File:** `agent/_default_tools.py:103`

`create_knowledge_search_tool(agent, run_response, run_context, knowledge_filters, enable_agentic_filters, async_mode)` returns a `Function` object registered with the model.

Two variants:
1. **Without agentic filters** (`enable_agentic_filters=False`, default): tool signature is `search_knowledge_base(query: str) -> str`.
2. **With agentic filters** (`enable_agentic_filters=True`): tool signature is `search_knowledge_base(query: str, filters: Optional[List[KnowledgeFilter]]) -> str`.

The function body calls `_messages.get_relevant_docs_from_knowledge(agent, query, filters, validate_filters, run_context)`. References (query, docs, elapsed time) are tracked in `run_response.references` (`_default_tools.py:130–139`).

---

### 1.7 Remote Loaders

**Directory:** `knowledge/loaders/` and `knowledge/remote_content/`

Remote content sources use `BaseStorageConfig` subclasses (`knowledge/remote_content/base.py`):

| Class | File | Source |
|---|---|---|
| `S3Config` | `s3.py` | AWS S3 |
| `GCSConfig` | `gcs.py` | Google Cloud Storage |
| `GitHubConfig` | `github.py` | GitHub repos (allowlisted `repo` param) |
| `SharePointConfig` | `sharepoint.py` | Microsoft SharePoint |
| `AzureBlobConfig` | `azure_blob.py` | Azure Blob Storage |

Each config exposes `.file(path)` and `.folder(path/)` factory methods that return `RemoteContent` objects. The router (`os/routers/knowledge/knowledge.py:340–350`) checks `is_folder = path.endswith("/")` and calls the appropriate factory.

**Cloud Loaders** (`knowledge/loaders/`): `AzureBlobLoader`, `GCSLoader`, `GitHubLoader`, `S3Loader`, `SharePointLoader` — these are iterator/streaming loaders used for bulk ingestion.

---

### 1.8 Rerankers

**Directory:** `knowledge/reranker/`

Base: `Reranker` (`reranker/base.py`) with method `rerank(query, documents) -> List[Document]`.

| Class | File | Provider |
|---|---|---|
| `CohereReranker` | `cohere.py` | Cohere rerank API |
| `AWSBedrockReranker` | `aws_bedrock.py` | AWS Bedrock |
| `InfinityReranker` | `infinity.py` | Infinity inference server |
| `SentenceTransformerReranker` | `sentence_transformer.py` | local cross-encoder |

VectorDBs that support reranking (e.g., `LanceDb`, `UpstashVectorDb`) call `self.reranker.rerank(query, search_results)` after the ANN search (`vectordb/lancedb/lance_db.py:547`).

---

## 2. Memory Subsystem

### 2.1 `MemoryManager` class

**File:** `memory/manager.py:45`

```python
class MemoryManager:
    model: Optional[Union[Model, str]] = None      # defaults to OpenAI gpt-4o (manager.py:113)
    system_message: Optional[str] = None
    memory_capture_instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    delete_memories: bool = False
    update_memories: bool = True
    add_memories: bool = True
    clear_memories: bool = False
    debug_mode: bool = False
```

`MemoryManager` is the main entry point. It is set on `Agent.memory_manager`. It does NOT hold memories in-process; it reads/writes entirely through `self.db`.

**Core methods:**

| Method | Line | Description |
|---|---|---|
| `get_user_memories(user_id)` | 165 | Reads from DB, returns `List[UserMemory]` |
| `add_user_memory(memory, user_id)` | 211 | UUID-assigns if no `memory_id`; upserts to DB |
| `replace_user_memory(memory_id, memory, user_id)` | 244 | Full replace; upserts to DB |
| `delete_user_memory(memory_id, user_id)` | 280 | Calls `db.delete_user_memory` |
| `clear_user_memories(user_id)` | 299 | Batch-deletes all memories for user |
| `create_user_memories(message, messages, ...)` | 368 | LLM extraction — creates/updates memories from conversation |
| `acreate_user_memories(...)` | 423 | Async counterpart |
| `update_memory_task(task, user_id)` | 481 | LLM-driven free-form task ("delete memory X", "add Y") |
| `search_user_memories(query, limit, retrieval_method, user_id)` | 588 | Retrieval: `last_n`, `first_n`, or `agentic` (LLM-ranked) |
| `optimize_memories(user_id, strategy, apply)` | 793 | Runs optimization strategy (e.g., Summarize), optionally writes back |
| `aoptimize_memories(...)` | 864 | Async counterpart |

`read_from_db(user_id)` (`manager.py:116`) loads the full user memory list, then groups into `Dict[user_id, List[UserMemory]]`. No in-process cache — every call hits the DB.

---

### 2.2 `UserMemory` schema

**File:** `db/schemas/memory.py:9`

```python
@dataclass
class UserMemory:
    memory: str                              # The actual memory text
    memory_id: Optional[str] = None
    topics: Optional[List[str]] = None
    user_id: Optional[str] = None
    input: Optional[str] = None             # Original user message that triggered extraction
    created_at: Optional[int] = None        # Unix epoch seconds (auto-set in __post_init__)
    updated_at: Optional[int] = None
    feedback: Optional[str] = None
    agent_id: Optional[str] = None          # Which agent created this memory
    team_id: Optional[str] = None
```

`__post_init__` normalizes `created_at` to epoch seconds via `now_epoch_s()`. `to_dict()` excludes `None` values; `from_dict()` handles ISO datetime strings by converting via `to_epoch_s`.

**Important distinction from `reference_belief_semantics.md`:** `UserMemory` is for the SYSTEM's stored observations about user behaviour and preferences (equivalent to LBM's `:Belief` pattern). NOT for user's own opinions (those would be `:Triple{predicate_category='belief'}`).

---

### 2.3 Memory injection into system prompt

**File:** `agent/_messages.py:287–325`

When `agent.add_memories_to_context = True`:

1. Calls `memory_manager.get_user_memories(user_id)`.
2. If memories exist, injects into system prompt:
   ```
   You have access to user info and preferences from previous interactions...
   <memories_from_previous_interactions>
   - {memory.memory}
   - ...
   </memories_from_previous_interactions>
   Note: this information is from previous interactions and may be updated...
   ```
3. If `agent.enable_agentic_memory = True`, also injects `<updating_user_memories>` block with instructions to use the `update_user_memory` tool.

The `update_user_memory` tool (`_default_tools.py:39`) is a closure over `agent.memory_manager.update_memory_task(task, user_id)` — the model describes what to do in natural language.

---

### 2.4 Memory creation (background task)

**File:** `agent/_managers.py`

Memory updates happen **after the agent response** via background threads/tasks:

**Async path** (`_managers.py:139–177`):
```python
async def astart_memory_task(agent, run_messages, user_id, existing_task) -> Optional[Task]:
    # Cancel any prior task from a retry
    # Creates asyncio.Task calling amake_memories(agent, run_messages, user_id)
```

**Sync path** (`_managers.py:180–215`):
```python
def start_memory_future(agent, run_messages, user_id, existing_future) -> Optional[Future]:
    # Uses agent.background_executor.submit(make_memories, ...)
```

Gate conditions (`_managers.py:165–173`):
- `run_messages.user_message is not None` OR `extra_messages` non-empty
- `agent.memory_manager is not None`
- `agent.update_memory_on_run = True`
- `not agent.enable_agentic_memory` — when agentic memory is on, the model manages via tool calls instead

`make_memories` (`_managers.py:29–81`) calls `memory_manager.create_user_memories(message=user_message_str, user_id, agent_id, run_metrics)`.

---

### 2.5 Memory DB storage backends

All memory storage backends implement the `BaseDb` abstract interface (`db/base.py:212–280`):

```python
# Memory-related abstract methods on BaseDb:
def clear_memories(self) -> None: ...
def delete_user_memory(self, memory_id, user_id) -> None: ...
def delete_user_memories(self, memory_ids, user_id) -> None: ...
def get_all_memory_topics(self, user_id) -> List[str]: ...
def get_user_memory(self, memory_id, ...) -> Optional[Union[UserMemory, dict]]: ...
def get_user_memories(self, user_id, ...) -> List[UserMemory]: ...
def upsert_user_memory(self, memory: UserMemory) -> None: ...
```

**Supported backends** (`db/` directory):

| Backend | Directory | Async variant |
|---|---|---|
| SQLite | `db/sqlite/` | `async_sqlite.py` |
| PostgreSQL | `db/postgres/` | `async_postgres.py` |
| MySQL | `db/mysql/` | `async_mysql.py` |
| MongoDB | `db/mongo/` | `async_mongo.py` |
| DynamoDB | `db/dynamo/` | — |
| Firestore | `db/firestore/` | — |
| Redis | `db/redis/` | — |
| SingleStore | `db/singlestore/` | — |
| SurrealDB | `db/surrealdb/` | — |
| In-Memory | `db/in_memory/` | — |
| JSON file | `db/json/` | — |
| GCS JSON | `db/gcs_json/` | — |

Default table name for memories: `"agno_memories"` (`db/base.py:59`).

Note: `BaseDb` is a unified backend — it stores sessions, memories, cultural knowledge, evals, metrics, learnings, and traces all in different tables within the same connection. Table names are configurable via constructor kwargs.

---

### 2.6 Memory summarization / optimization

**File:** `memory/manager.py:793` and `memory/strategies/`

`optimize_memories(user_id, strategy, apply)` flow:
1. Loads all memories for `user_id`.
2. Resolves strategy: `MemoryOptimizationStrategyType.SUMMARIZE` → `SummarizeStrategy`.
3. Calls `strategy_instance.optimize(memories, model)` → `List[UserMemory]` (usually 1 memory).
4. If `apply=True`: clears all existing memories via `clear_user_memories`, then upserts optimized memories.

**`SummarizeStrategy`** (`memory/strategies/summarize.py:15`):

- Combines all memory texts: `"Memory 1: ...\n\nMemory 2: ..."`.
- Calls `model.response([system_msg, user_msg])`.
- Collects union of all `topics`.
- Returns single `UserMemory` with new `memory_id` (UUID4).
- Async variant uses `await model.aresponse(...)`.
- Base class `MemoryOptimizationStrategy` (`strategies/base.py`) has `count_tokens(memories)` for reporting.

---

### 2.7 `create_session_summary`

**File:** `session/summary.py:227`

```python
def create_session_summary(self, session, run_metrics) -> Optional[SessionSummary]:
```

Called from `SessionSummarizer` which is configured on the agent. Flow:

1. `_prepare_summary_messages(session)`:
   - Calls `session.get_messages(last_n_runs=self.last_n_runs, limit=self.conversation_limit)`.
   - Builds `[system_message, Message(role="user", content=self.summary_request_message)]`.
   - Returns `None` if no meaningful messages (skips summary generation).

2. `get_response_format(model)`:
   - Uses `SessionSummaryResponse` Pydantic model.
   - Prefers native structured outputs → JSON schema → `{"type": "json_object"}`.

3. `model.response(messages, response_format)` → raw response.

4. `_process_summary_response(response, model)`:
   - Handles both `response.parsed` (native) and `response.content` (string JSON parse via `parse_response_model_str`).
   - Returns `SessionSummary(summary=..., topics=..., updated_at=datetime.now())`.

5. Sets `session.summary = session_summary`.

**System prompt injection** (`_messages.py:389–397`): When `agent.add_session_summary_to_context=True` and `session.summary` exists:
```
Here is a brief summary of your previous interactions:
<summary_of_previous_interactions>
{session.summary.summary}
</summary_of_previous_interactions>
Note: this information is from previous interactions and may be outdated...
```

---

## 3. VectorDB Subsystem

### 3.1 `VectorDb` base interface

**File:** `vectordb/base.py:9`

```python
class VectorDb(ABC):
    def __init__(self, *, id, name, description, similarity_threshold): ...

    @abstractmethod def create(self) -> None: ...
    @abstractmethod async def async_create(self) -> None: ...
    @abstractmethod def name_exists(self, name: str) -> bool: ...
    @abstractmethod def id_exists(self, id: str) -> bool: ...
    @abstractmethod def content_hash_exists(self, content_hash: str) -> bool: ...
    @abstractmethod def insert(self, content_hash, docs, filters) -> None: ...
    @abstractmethod async def async_insert(self, content_hash, docs, filters) -> None: ...
    def upsert_available(self) -> bool: return False   # default; override to True
    @abstractmethod def upsert(self, content_hash, docs, filters) -> None: ...
    @abstractmethod async def async_upsert(self, content_hash, docs, filters) -> None: ...
    @abstractmethod def search(self, query, limit=5, filters=None) -> List[Document]: ...
    @abstractmethod async def async_search(self, query, limit=5, filters=None) -> List[Document]: ...
    @abstractmethod def drop(self) -> None: ...
    @abstractmethod def delete(self) -> bool: ...
    @abstractmethod def delete_by_id(self, id) -> bool: ...
    @abstractmethod def delete_by_name(self, name) -> bool: ...
    @abstractmethod def delete_by_metadata(self, metadata) -> bool: ...
    @abstractmethod def delete_by_content_id(self, content_id) -> bool: ...
    def update_metadata(self, content_id, metadata) -> None: ...  # default logs warning
    @abstractmethod def get_supported_search_types(self) -> List[str]: ...
```

`similarity_threshold` (`base.py:19–29`): Must be in [0.0, 1.0]. Used by backends that support it (e.g., PgVector) to filter results below a minimum similarity score.

---

### 3.2 Complete backend listing

All backends extend `VectorDb`. Discovered from `vectordb/` directory and `codegraph_explore` extends relationships:

| Backend class | Module | Notes |
|---|---|---|
| `PgVector` | `vectordb/pgvector/pgvector.py` | PostgreSQL + pgvector; SQLAlchemy; HNSW/IVFFlat indexes |
| `Qdrant` | `vectordb/qdrant/qdrant.py` | Qdrant; supports dense/sparse/hybrid; BM25 sparse default |
| `ChromaDb` | `vectordb/chroma/chromadb.py` | ChromaDB; vector/keyword/hybrid search |
| `Milvus` | `vectordb/milvus/milvus.py` | Milvus; supports hybrid; full async |
| `MongoDb` | `vectordb/mongodb/mongodb.py` | MongoDB Atlas Vector Search |
| `LanceDb` | `vectordb/lancedb/lance_db.py` | LanceDB; vector/keyword/hybrid; async wraps sync |
| `RedisDB` | `vectordb/redis/redisdb.py` | Redis Stack vector index |
| `Cassandra` | `vectordb/cassandra/cassandra.py` | Apache Cassandra / DataStax Astra |
| `Clickhouse` | `vectordb/clickhouse/clickhousedb.py` | ClickHouse; full async |
| `CouchbaseSearch` | `vectordb/couchbase/couchbase.py` | Couchbase FTS + vector |
| `SingleStore` | `vectordb/singlestore/singlestore.py` | SingleStoreDB |
| `SurrealDb` | `vectordb/surrealdb/surrealdb.py` | SurrealDB |
| `UpstashVectorDb` | `vectordb/upstashdb/upstashdb.py` | Upstash Vector; no insert (upsert only) |
| `Weaviate` | `vectordb/weaviate/weaviate.py` | Weaviate |
| `LangChainVectorDb` | `vectordb/langchaindb/langchaindb.py` | Wraps any LangChain vectorstore |
| `LlamaIndexVectorDb` | `vectordb/llamaindex/llamaindexdb.py` | Wraps any LlamaIndex vectorstore |
| `LightRag` | `vectordb/lightrag/lightrag.py` | LightRAG graph+vector hybrid |

**19 backends** total (including 2 adapter/wrapper classes for LangChain and LlamaIndex).

---

### 3.3 Distance metrics & score normalization

**File:** `vectordb/distance.py:4`

```python
class Distance(str, Enum):
    cosine = "cosine"
    l2 = "l2"
    max_inner_product = "max_inner_product"
```

**Score normalization** (`vectordb/score.py`):

| Metric | Raw value | Normalized formula |
|---|---|---|
| `cosine` | distance ∈ [0, 2] | `max(0, min(1, 1.0 - distance))` |
| `l2` | Euclidean distance ∈ [0, ∞) | `1.0 / (1.0 + distance)` |
| `max_inner_product` | inner product ∈ [-1, 1] | `max(0, min(1, (ip + 1.0) / 2.0))` |

`normalize_score(distance, metric) -> float` and `score_to_distance_threshold(similarity, metric) -> float` provide round-trip conversion (used by PgVector's `similarity_threshold` filter).

---

### 3.4 Search types

**File:** `vectordb/search.py:4`

```python
class SearchType(str, Enum):
    vector = "vector"       # pure ANN / embedding similarity
    keyword = "keyword"     # BM25 / full-text search
    hybrid = "hybrid"       # combination of both
```

Set per VectorDb instance: `PgVector(search_type=SearchType.hybrid)`. `Knowledge.search()` can override `search_type` per-query via the `search_type` parameter (`knowledge/knowledge.py:521–526`).

**Hybrid fusion strategies** (where supported):
- Qdrant: `models.Fusion.RRF` (Reciprocal Rank Fusion, default) or `models.Fusion.DBSF`
- PgVector: `vector_score_weight: float = 0.5` for blending

---

### 3.5 PgVector (annotated)

**File:** `vectordb/pgvector/pgvector.py:40`

Key constructor fields:
```python
class PgVector(VectorDb):
    table_name: str
    schema: str = "ai"
    embedder: Optional[Embedder]
    search_type: SearchType = SearchType.vector
    vector_index: Union[Ivfflat, HNSW] = HNSW()          # index type for ANN
    distance: Distance = Distance.cosine
    prefix_match: bool = False                             # enable prefix full-text
    vector_score_weight: float = 0.5                       # hybrid blend
    content_language: str = "english"                      # FTS language
    similarity_threshold: Optional[float] = None           # post-filter by similarity
```

Index types (`vectordb/pgvector/index.py`):
- `HNSW`: `m=16, ef_construction=64` defaults; uses `pgvector`'s HNSW.
- `Ivfflat`: traditional IVF with flat quantization.

Uses SQLAlchemy. Schema: column `embedding Vector(dimensions)`, plus `id`, `name`, `meta_data` JSONB, `content`, `content_id`, `content_hash`, `usage` JSONB.

---

### 3.6 Qdrant (annotated)

**File:** `vectordb/qdrant/qdrant.py:26`

Key constructor fields:
```python
class Qdrant(VectorDb):
    collection: str
    embedder: Optional[Embedder]
    distance: Distance = Distance.cosine
    location: Optional[str]                   # ":memory:" for in-process
    url / host / port: ...                    # connection
    api_key: Optional[str]                    # Qdrant Cloud
    search_type: SearchType = SearchType.vector
    dense_vector_name: str = "dense"
    sparse_vector_name: str = "sparse"
    hybrid_fusion_strategy: models.Fusion = models.Fusion.RRF
    fastembed_kwargs: Optional[dict]          # for offline sparse embedding
```

For hybrid search, uses Qdrant's named vectors: dense (embedding model) + sparse (BM25 via `fastembed`). Fusion via `models.Fusion.RRF` (default) or `DBSF`.

Both sync (`QdrantClient`) and async (`AsyncQdrantClient`) clients are instantiated.

---

### 3.7 Embedding flow: Document → embed → upsert

The canonical flow for all VectorDB backends:

```
Knowledge._load_from_path/url/content(content, upsert, skip_if_exists)
  → reader.read(source) → raw_documents: List[Document]
  → chunk(doc) per strategy → chunked_documents: List[Document]
  → _prepare_documents_for_insert(docs, content_id, metadata)
      → doc.content_id = content_id (for later deletion by content)
      → merge metadata
  → vector_db.upsert(content_hash, docs)  OR  vector_db.insert(content_hash, docs)
      → for doc in docs:
            doc.embed(embedder=self.embedder)
            # doc.embedding = embedder.get_embedding_and_usage(doc.content)[0]
            store {id, name, content, content_id, content_hash, meta_data, embedding, usage}
```

The `content_hash` is computed per-content-item (SHA-256 of path/url/text + metadata) and stored in each vector record to support `content_hash_exists()` deduplication and `delete_by_content_id()`.

---

## 4. Session Subsystem

### 4.1 `AgentSession` dataclass

**File:** `session/agent.py:15`

```python
@dataclass
class AgentSession:
    session_id: str                              # UUID (primary key)
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    user_id: Optional[str] = None
    workflow_id: Optional[str] = None
    session_data: Optional[Dict[str, Any]] = None   # blob — see §4.2
    metadata: Optional[Dict[str, Any]] = None
    agent_data: Optional[Dict[str, Any]] = None      # agent_id, name, model
    runs: Optional[List[Union[RunOutput, TeamRunOutput]]] = None
    summary: Optional[SessionSummary] = None
    created_at: Optional[int] = None                 # Unix epoch seconds
    updated_at: Optional[int] = None
```

The `runs` list holds ALL run outputs for the session. Each `RunOutput` contains `messages`, `run_id`, `agent_id`, `status`, `parent_run_id`, and tool call metadata.

---

### 4.2 `session_data` blob — what lives inside it

`session_data` is an untyped `Dict[str, Any]` JSON blob stored in the database. Keys in use across the codebase (discovered from `utils/agent.py`, `os/schema.py`):

| Key | Type | Description |
|---|---|---|
| `session_name` | `str` | Human-readable name (set by user or auto-generated) |
| `session_state` | `Dict[str, Any]` | Arbitrary key-value pairs persisted across runs |
| `session_metrics` | `Dict` / `SessionMetrics` | Token counts, cost, etc. for the whole session |
| `images` | `List` | Images shared in session |
| `videos` | `List` | Videos shared in session |
| `audio` | `List` | Audio shared in session |

`AgentSessionDetailSchema.from_session()` (`os/schema.py:336`) exposes `session_state` and `session_metrics` as first-class fields in the REST response.

---

### 4.3 Session storage (BaseDb)

Session is persisted via `BaseDb.upsert_session(session, deserialize)` (`db/base.py:197`). All DB backends implement this. The session is serialized to a JSON blob before storage and deserialized on read via `AgentSession.from_dict()` / `AgentSession.to_dict()`.

`session/agent.py:46–52` (`to_dict`): Serializes `runs` (list of dicts) and `summary` (dict).
`session/agent.py:55–88` (`from_dict`): Reconstructs `RunOutput` vs `TeamRunOutput` based on whether `"agent_id"` or `"team_id"` is present in each run dict.

Sessions can be loaded from any supported backend: SQLite, Postgres, MySQL, MongoDB, DynamoDB, Firestore, Redis, SurrealDB, SingleStore, in-memory, JSON file, GCS JSON.

---

### 4.4 Session lifecycle in the agent

**File:** `agent/_session.py`

```
Agent.run(message, session_id, user_id)
  → initialize_session(agent, session_id, user_id)       # _session.py:46
      → assigns UUID if session_id is None
      → sets agent.session_id for sticky reuse
  → get_session(agent, session_id, user_id)              # _session.py:75
      → checks agent._cached_session first (if cache_session=True)
      → loads from agent.storage (BaseDb) via db.get_session(session_id)
      → if not found: creates new AgentSession(session_id=...)
  → run main model loop
  → upsert_session(agent, session, run_output)           # _session.py (save path)
      → session.upsert_run(run_output)                   # agent.py:90
      → db.upsert_session(session)
```

Session caching: if `agent.cache_session=True`, the loaded session is stored in `agent._cached_session`. Subsequent calls within the same Python process skip the DB read if `session_id` matches.

---

### 4.5 `session_state` access utilities

**File:** `utils/agent.py:820–891`

`session_state` is the persistent key-value store for workflow/agent state across runs.

```python
def get_session_state_util(entity, session_id) -> Dict[str, Any]:
    session = entity.get_session(session_id)
    return session.session_data.get("session_state", {})

def update_session_state_util(entity, session_state_updates, session_id) -> dict:
    session.session_data["session_state"].update(session_state_updates)
    entity.save_session(session=session)
    return session.session_data["session_state"]
```

**Note from `feedback_agno_api_usage.md`:** The `session_state` caveat — if your agent uses `session_state`, you must ensure the session is loaded before the run (not just initialized), otherwise state from a prior run may not be available.

Async variants `aget_session_state_util` and `aupdate_session_state_util` are provided. `_has_async_db` (`utils/agent.py`) guards sync utilities from being called with async DB backends.

---

## 5. Cross-Cutting: How Everything Wires Together

```
Agent(
    knowledge=Knowledge(
        vector_db=PgVector(table_name="docs", embedder=OpenAIEmbedder()),
        contents_db=SqliteDb("agno.db"),
        max_results=10,
    ),
    memory_manager=MemoryManager(
        db=SqliteDb("agno.db"),
        model="openai:gpt-4o-mini",
    ),
    storage=SqliteDb("agno.db"),         # same db can serve all three roles
    session_id="...",
    user_id="...",
    add_memories_to_context=True,
    search_knowledge=True,
    update_memory_on_run=True,
)
```

**Run-time sequence (simplified):**

```
Agent.run(message)
│
├── [1] initialize_session → session_id (UUID)
│
├── [2] get_session(session_id)
│       └── db.get_session → AgentSession (with prior runs + summary)
│
├── [3] get_system_message(agent, session, run_context)
│       ├── Inject memories: memory_manager.get_user_memories(user_id)
│       │       → db.get_user_memories → List[UserMemory]
│       │       → format into <memories_from_previous_interactions>
│       ├── Inject session summary: session.summary.summary (if exists)
│       └── Register search_knowledge_base tool (if search_knowledge=True)
│
├── [4] model.response(messages=[system_msg, history_msgs, user_msg])
│       └── model calls search_knowledge_base(query)  [if search_knowledge=True]
│               → knowledge.search(query, max_results, filters)
│                       → vector_db.search(query, limit)
│                               → embedder.get_embedding(query)
│                               → ANN search → List[Document]
│               → format → str → returned to model
│
├── [5] session.upsert_run(run_output) → db.upsert_session(session)
│
├── [6] BACKGROUND: start_memory_future / astart_memory_task
│       └── memory_manager.create_user_memories(user_message, user_id)
│               → LLM extracts memories → db.upsert_user_memory(...)
│
└── [7] (optional) session_summarizer.create_session_summary(session)
        → LLM summarizes messages → session.summary updated
        → db.upsert_session(session)
```

**Isolation patterns:**
- Multiple knowledge bases sharing one VectorDB: use `isolate_vector_search=True` + distinct `name` → injects `linked_to` filter automatically.
- Multi-agent shared DB: all agents share the same `BaseDb`; memory scoped by `user_id`; sessions scoped by `session_id` + `agent_id`; knowledge scoped by `content_id` / `content_hash`.
- Agent ID on memories: `UserMemory.agent_id` tracks which agent created each memory; `memory_manager.create_user_memories(agent_id=agent.id)` passes this through.

---

*Generated by codegraph + source analysis. File:line citations reference Agno 2.6.9 as indexed.*
