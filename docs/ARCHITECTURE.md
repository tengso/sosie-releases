# Sosie Architecture

## Component Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         API Server (port 8001)                      │
│  - HTTP endpoints for frontend                                      │
│  - Delegates to IndexerProcess for mutations                        │
│  - Direct DB reads for queries (read-only)                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ delegates
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         IndexerProcess                               │
│  - OWNS database persistence for roots                              │
│  - Coordinates parsing, chunking, embedding                         │
│  - Manages VectorStore                                              │
│  - Controls WatcherProcess lifecycle                                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ owns/controls
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         WatcherProcess                               │
│  - File system monitoring (watchdog)                                │
│  - In-memory root management                                        │
│  - Event batching and queuing                                       │
│  - NO database writes (reads persisted roots on startup)            │
└─────────────────────────────────────────────────────────────────────┘
```

## Database Ownership

| Table | Owner | Notes |
|-------|-------|-------|
| `roots` | IndexerProcess | Root folder persistence |
| `documents` | VectorStore | Indexed document metadata |
| `chunks` | VectorStore | Document chunks |
| `embeddings` | VectorStore | Chunk embeddings |
| `activity_log` | IndexerProcess | Activity logging |
| `watcher_status` | WatcherProcess | Running status flag only |
| `commands` | WatcherProcess | Command queue |
| `events` | WatcherProcess | Event queue |

---

## Component Interfaces

### IndexerProcess

**Responsibility:** Main orchestrator for document indexing. Owns database persistence for roots.

#### Public Interface

```python
class IndexerProcess:
    # Lifecycle
    def start(self) -> None                    # Start blocking
    def start_async(self) -> None              # Start in background
    def stop(self) -> None                     # Stop gracefully
    def close(self) -> None                    # Close and cleanup
    
    # Root Management (OWNS database persistence)
    def add_root(self, root: Path) -> bool     # Add root, returns False if exists
    def remove_root(self, root: Path) -> None  # Remove root and its documents
    def get_roots(self) -> List[Path]          # Get watched roots
    
    # Indexing
    def index_file(self, path: Path) -> IndexerEvent
    def remove_file(self, path: Path) -> IndexerEvent
    def resync(self) -> None                   # Full resync
    def integrity_check(self) -> None          # Run integrity check
    
    # Search
    def search(self, query: str, top_k: int = 10, ...) -> List[SearchResult]
    def get_context_for_query(self, query: str, ...) -> str
    
    # Stats
    def get_stats(self) -> dict
    def build_integrity_report(self, max_items: int = 10) -> dict
```

#### Interaction Rules

1. **add_root()** - Checks database, inserts if new, then tells watcher to watch
2. **remove_root()** - Removes from vector store, deletes from database, tells watcher to stop
3. Only IndexerProcess should INSERT/DELETE from `roots` table

---

### WatcherProcess

**Responsibility:** File system monitoring. Manages in-memory state and file observers.

#### Public Interface

```python
class WatcherProcess:
    # Lifecycle
    def start(self) -> None                    # Start blocking
    def start_async(self) -> None              # Start in background  
    def stop(self) -> None                     # Stop gracefully
    
    # Root Management (in-memory only, NO database writes)
    def add_root(self, root: Path) -> None     # Queue command to add root
    def remove_root(self, root: Path) -> None  # Queue command to remove root
    def get_roots(self) -> List[Path]          # Get currently watched roots
    
    # Commands
    def resync(self) -> None                   # Queue resync command
    def integrity_check(self) -> None          # Queue integrity check
    
    # Events
    def iter_events(self, batch_size: int = 1) -> Iterator[FileEvent]
    def iter_batches(self) -> Iterator[EventBatch]
    def get_pending_events(self, max_count: int = 100) -> List[FileEvent]
    
    # Static
    @staticmethod
    def check_running(db_path: Path) -> bool   # Check if watcher is running
```

#### Interaction Rules

1. **add_root()** - Queues ADD_ROOT command, internal handler starts watching
2. **_add_root_internal()** - Adds to RootManager, starts FSWatcher, emits event
3. **NO database writes** for roots - IndexerProcess owns that
4. Reads persisted roots from database on startup via `_load_persisted_roots()`

---

### IndexerAPIServer

**Responsibility:** HTTP API for frontend. Delegates mutations to IndexerProcess.

#### Endpoints

| Method | Path | Handler | Notes |
|--------|------|---------|-------|
| POST | `/api/settings/roots` | `_settings_add_root` | Delegates to IndexerProcess |
| DELETE | `/api/settings/roots` | `_settings_remove_root` | Delegates to IndexerProcess |
| GET | `/api/settings/roots` | `_settings_get_roots` | Direct DB read |
| GET | `/api/dashboard/*` | various | Direct DB reads |
| POST | `/api/search` | `_search_chunks` | Uses VectorStore |

#### Interaction Rules

1. **Mutations** (add/remove root, resync) → Delegate to `IndexerProcess`
2. **Queries** (stats, roots list, search) → Direct database reads OK
3. **NEVER** insert/update/delete roots directly - always via IndexerProcess

---

## Interaction Sequence Diagrams

### Add Root

```
Frontend                API Server              IndexerProcess           WatcherProcess
   │                        │                         │                        │
   │  POST /api/settings/roots                        │                        │
   │───────────────────────>│                         │                        │
   │                        │                         │                        │
   │                        │  add_root(path)         │                        │
   │                        │────────────────────────>│                        │
   │                        │                         │                        │
   │                        │                         │  1. Check DB           │
   │                        │                         │  2. INSERT INTO roots  │
   │                        │                         │  3. Log activity       │
   │                        │                         │                        │
   │                        │                         │  add_root(path)        │
   │                        │                         │───────────────────────>│
   │                        │                         │                        │
   │                        │                         │                        │  Queue ADD_ROOT cmd
   │                        │                         │                        │  ─────────────────>
   │                        │                         │                        │
   │                        │                         │  4. Start scan thread  │
   │                        │                         │                        │
   │                        │  return True/False      │                        │
   │                        │<────────────────────────│                        │
   │                        │                         │                        │
   │  200 OK / 409 Conflict │                         │                        │
   │<───────────────────────│                         │                        │
```

### Remove Root

```
Frontend                API Server              IndexerProcess           WatcherProcess
   │                        │                         │                        │
   │  DELETE /api/settings/roots?path=...             │                        │
   │───────────────────────>│                         │                        │
   │                        │                         │                        │
   │                        │  remove_root(path)      │                        │
   │                        │────────────────────────>│                        │
   │                        │                         │                        │
   │                        │                         │  1. Remove from VectorStore
   │                        │                         │  2. DELETE FROM roots  │
   │                        │                         │  3. Log activity       │
   │                        │                         │                        │
   │                        │                         │  remove_root(path)     │
   │                        │                         │───────────────────────>│
   │                        │                         │                        │
   │                        │                         │                        │  Queue REMOVE_ROOT
   │                        │                         │                        │  ─────────────────>
   │                        │                         │                        │
   │                        │  return                 │                        │
   │                        │<────────────────────────│                        │
   │                        │                         │                        │
   │  200 OK                │                         │                        │
   │<───────────────────────│                         │                        │
```

### File Change Event

```
FileSystem              WatcherProcess           IndexerProcess
   │                        │                         │
   │  file modified         │                         │
   │───────────────────────>│                         │
   │                        │                         │
   │                        │  1. Debounce           │
   │                        │  2. Create FileEvent    │
   │                        │  3. Queue EventBatch    │
   │                        │                         │
   │                        │         ┌───────────────┘
   │                        │         │ _process_loop polls
   │                        │         ▼
   │                        │  get_pending_events()   │
   │                        │<────────────────────────│
   │                        │                         │
   │                        │  [FileEvent]            │
   │                        │────────────────────────>│
   │                        │                         │
   │                        │                         │  index_file(path)
   │                        │                         │  ─────────────────>
```

---

## Anti-Patterns to Avoid

### ❌ API Server doing database writes for roots

```python
# WRONG - API server should NOT insert roots
def _settings_add_root(self, payload):
    wdb.execute("INSERT INTO roots ...")  # NO!
    self._queue_root_command(path, "add")
```

### ✅ Correct - delegate to IndexerProcess

```python
# CORRECT - delegate to IndexerProcess which owns the database
def _settings_add_root(self, payload):
    error = self._queue_root_command(path, "add")  # This calls indexer.add_root()
    if error:
        return _json(self, 500, {"error": error})
```

### ❌ Watcher doing database writes for roots

```python
# WRONG - Watcher should NOT save roots
def _add_root_internal(self, root):
    self._root_manager.add_root(root)
    self._save_root(root)  # NO! IndexerProcess already did this
```

### ✅ Correct - Watcher only manages in-memory state

```python
# CORRECT - Watcher only manages watching, not persistence
def _add_root_internal(self, root):
    self._root_manager.add_root(root)
    # Don't save to database - IndexerProcess.add_root() already did that
    self._fs_watcher_pool.start_watching(root)
```

---

## Summary

| Component | Database Writes | Database Reads |
|-----------|-----------------|----------------|
| IndexerProcess | roots, activity_log, documents, chunks, embeddings | All |
| WatcherProcess | watcher_status, commands, events | roots (on startup) |
| API Server | None | All (for queries) |
