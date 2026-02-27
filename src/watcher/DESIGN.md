# File Watcher Package - Detailed Design

## Overview

A file watcher process that monitors root folders for file system changes and produces structured events via a persistent queue.

---

## Requirements Summary

| Requirement | Description |
|-------------|-------------|
| **Input** | List of root folders (dynamically changeable) |
| **Output** | File change events: `ADD`, `DELETE`, `UPDATE`, `MOVE` |
| **Move semantics** | Files moved out of all roots → treated as `DELETE` |
| **Queue** | Persistent queue for both input commands and output events |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        WatcherProcess                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ CommandQueue │───▶│ RootManager  │───▶│ FSWatcherPool    │  │
│  │  (Input)     │    │              │    │ (per-root)       │  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
│                                                   │             │
│                                                   ▼             │
│                      ┌──────────────┐    ┌──────────────────┐  │
│                      │ EventQueue   │◀───│ EventProcessor   │  │
│                      │  (Output)    │    │ (dedup, move)    │  │
│                      └──────────────┘    └──────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Data Models (`models.py`)

```python
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import time

class EventType(Enum):
    ADD = "add"
    DELETE = "delete"
    UPDATE = "update"
    MOVE = "move"

class CommandType(Enum):
    ADD_ROOT = "add_root"
    REMOVE_ROOT = "remove_root"
    SHUTDOWN = "shutdown"

@dataclass(frozen=True)
class FileEvent:
    event_type: EventType
    path: Path
    root: Path                      # Which root this file belongs to
    old_path: Optional[Path] = None # For MOVE events
    old_root: Optional[Path] = None # For cross-root MOVE
    timestamp: float = field(default_factory=time.time)
    
@dataclass(frozen=True)
class WatcherCommand:
    command_type: CommandType
    root: Optional[Path] = None
    timestamp: float = field(default_factory=time.time)
```

### 2. Persistent Queue (`queue.py`)

SQLite-backed persistent queue for durability across restarts.

```python
class PersistentQueue:
    """
    SQLite-backed FIFO queue with:
    - Atomic enqueue/dequeue
    - Crash recovery
    - Optional batching
    """
    
    def __init__(self, db_path: Path, table_name: str): ...
    def enqueue(self, item: bytes) -> int: ...
    def dequeue(self, batch_size: int = 1) -> List[Tuple[int, bytes]]: ...
    def ack(self, ids: List[int]) -> None: ...  # Mark as processed
    def requeue_unacked(self) -> int: ...       # Recovery on restart
    def close(self) -> None: ...
```

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload BLOB NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, processing, done
    created_at REAL,
    updated_at REAL
);
CREATE INDEX idx_status ON queue(status);
```

### 3. Root Manager (`root_manager.py`)

Manages the set of watched root folders.

```python
class RootManager:
    """
    Thread-safe management of root folders.
    """
    
    def __init__(self): ...
    def add_root(self, path: Path) -> bool: ...
    def remove_root(self, path: Path) -> bool: ...
    def get_roots(self) -> FrozenSet[Path]: ...
    def find_root_for_path(self, path: Path) -> Optional[Path]: ...
    def is_under_any_root(self, path: Path) -> bool: ...
```

### 4. File System Watcher Pool (`fs_watcher.py`)

One watcher per root using `watchdog` library.

```python
class FSWatcherPool:
    """
    Manages multiple watchdog observers, one per root.
    """
    
    def __init__(self, event_callback: Callable[[RawFSEvent], None]): ...
    def start_watching(self, root: Path) -> None: ...
    def stop_watching(self, root: Path) -> None: ...
    def stop_all(self) -> None: ...

@dataclass
class RawFSEvent:
    """Raw event from watchdog before processing."""
    event_type: str  # created, deleted, modified, moved
    src_path: Path
    dest_path: Optional[Path]  # For moves
    is_directory: bool
    timestamp: float
```

### 5. Event Processor (`event_processor.py`)

Transforms raw FS events into semantic `FileEvent` objects.

```python
class EventProcessor:
    """
    Processes raw filesystem events into semantic FileEvents.
    
    Responsibilities:
    - Deduplication (coalesce rapid changes)
    - Move detection (DELETE + ADD with same inode → MOVE)
    - Cross-root move handling (move out of all roots → DELETE)
    - Directory recursion (dir delete → individual file deletes)
    """
    
    def __init__(self, root_manager: RootManager, output_queue: PersistentQueue): ...
    def process(self, raw_event: RawFSEvent) -> None: ...
    def flush(self) -> None: ...  # Flush pending events after debounce window
```

**Key Logic - Move Detection:**

```python
def _detect_move(self, delete_event, add_event) -> bool:
    """
    Correlate DELETE + ADD events:
    1. Same filename within short time window
    2. Optionally verify via inode (platform-specific)
    """
    ...

def _handle_move(self, src: Path, dest: Path) -> FileEvent:
    """
    Determine move semantics:
    - Both in roots: MOVE event
    - src in root, dest outside: DELETE event
    - src outside, dest in root: ADD event (shouldn't happen normally)
    """
    src_root = self.root_manager.find_root_for_path(src)
    dest_root = self.root_manager.find_root_for_path(dest)
    
    if src_root and dest_root:
        return FileEvent(EventType.MOVE, dest, dest_root, old_path=src, old_root=src_root)
    elif src_root and not dest_root:
        return FileEvent(EventType.DELETE, src, src_root)
    elif not src_root and dest_root:
        return FileEvent(EventType.ADD, dest, dest_root)
```

### 6. Watcher Process (`process.py`)

Main orchestrator that ties everything together.

```python
class WatcherProcess:
    """
    Main entry point. Runs as a long-lived process.
    """
    
    def __init__(self, 
                 db_path: Path,
                 initial_roots: Optional[List[Path]] = None): ...
    
    def start(self) -> None:
        """Start the watcher process (blocking)."""
        ...
    
    def stop(self) -> None:
        """Graceful shutdown."""
        ...
    
    # Internal threads/tasks:
    # 1. Command consumer - reads from command queue
    # 2. Event processor - handles raw FS events
    # 3. Debounce flusher - periodic flush of coalesced events
```

---

## Event Flow

```
1. User adds root via CommandQueue
   └─▶ WatcherProcess reads command
       └─▶ RootManager.add_root()
           └─▶ FSWatcherPool.start_watching()

2. File system change occurs
   └─▶ watchdog emits raw event
       └─▶ FSWatcherPool forwards to EventProcessor
           └─▶ EventProcessor transforms & deduplicates
               └─▶ FileEvent enqueued to EventQueue

3. Consumer reads from EventQueue
   └─▶ Process event
       └─▶ Ack to remove from queue
```

---

## Move Detection Strategy

### Challenge
File system APIs often report moves as separate DELETE + CREATE events.

### Solution: Correlation Window

```python
MOVE_CORRELATION_WINDOW_MS = 100  # Configurable

class MoveCorrelator:
    def __init__(self):
        self._pending_deletes: Dict[str, Tuple[Path, float]] = {}  # filename -> (path, time)
    
    def on_delete(self, path: Path, timestamp: float) -> Optional[FileEvent]:
        filename = path.name
        self._pending_deletes[filename] = (path, timestamp)
        # Schedule check after window expires
        return None  # Defer event
    
    def on_create(self, path: Path, timestamp: float) -> Optional[FileEvent]:
        filename = path.name
        if filename in self._pending_deletes:
            old_path, delete_time = self._pending_deletes.pop(filename)
            if timestamp - delete_time < MOVE_CORRELATION_WINDOW_MS / 1000:
                return self._handle_move(old_path, path)
        return FileEvent(EventType.ADD, path, ...)
    
    def flush_expired(self) -> List[FileEvent]:
        """Emit DELETE events for unmatched deletes after window expires."""
        ...
```

---

## Deduplication Strategy

Rapid file changes (e.g., editor save) can cause event storms.

```python
DEBOUNCE_WINDOW_MS = 50

class EventDebouncer:
    def __init__(self):
        self._pending: Dict[Path, Tuple[EventType, float]] = {}
    
    def add(self, path: Path, event_type: EventType, timestamp: float):
        """
        Coalescing rules:
        - Multiple UPDATEs → single UPDATE
        - ADD then UPDATE → single ADD
        - ADD then DELETE → no event (cancel out)
        - DELETE then ADD → UPDATE (file replaced)
        """
        ...
    
    def flush(self) -> List[FileEvent]:
        """Return events older than debounce window."""
        ...
```

---

## Thread Model

```
┌─────────────────────────────────────────────────────────────┐
│                      Main Thread                            │
│  - Startup/shutdown coordination                            │
│  - Signal handling                                          │
└─────────────────────────────────────────────────────────────┘
        │
        ├──▶ CommandConsumerThread
        │      - Polls CommandQueue
        │      - Updates RootManager
        │      - Controls FSWatcherPool
        │
        ├──▶ WatchdogObserverThreads (N, managed by watchdog)
        │      - One per root
        │      - Emits raw events to queue
        │
        ├──▶ EventProcessorThread
        │      - Reads from internal raw event queue
        │      - Runs MoveCorrelator + EventDebouncer
        │      - Writes to EventQueue
        │
        └──▶ FlushThread
               - Periodic timer (e.g., every 100ms)
               - Flushes debounced/correlated events
```

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Root folder deleted | Emit DELETE for all tracked files, remove root |
| Root folder renamed | Treat as DELETE of old root + potential ADD if renamed within another root |
| Permission denied | Log warning, skip file, continue watching |
| Queue corruption | Rebuild from WAL or start fresh with warning |
| Watchdog crash | Restart observer for affected root |

---

## Configuration

```python
@dataclass
class WatcherConfig:
    db_path: Path = Path("watcher.db")
    debounce_ms: int = 50
    move_correlation_ms: int = 100
    flush_interval_ms: int = 100
    ignore_patterns: List[str] = field(default_factory=lambda: [
        "*.tmp", "*.swp", ".git/*", "__pycache__/*"
    ])
    recursive: bool = True
    follow_symlinks: bool = False
```

---

## File Structure

```
src/watcher/
├── __init__.py          # Public API exports
├── models.py            # Data classes (FileEvent, WatcherCommand, etc.)
├── queue.py             # PersistentQueue implementation
├── root_manager.py      # Root folder management
├── fs_watcher.py        # FSWatcherPool (watchdog wrapper)
├── event_processor.py   # EventProcessor, MoveCorrelator, EventDebouncer
├── process.py           # WatcherProcess main orchestrator
├── config.py            # WatcherConfig
└── exceptions.py        # Custom exceptions
```

---

## Public API

```python
from watcher import WatcherProcess, FileEvent, EventType

# Create and start
watcher = WatcherProcess(db_path=Path("./watcher.db"))
watcher.add_root(Path("/home/user/docs"))
watcher.start()  # Blocks, or use start_async()

# In another process/thread, consume events:
for event in watcher.iter_events():
    print(f"{event.event_type}: {event.path}")
    watcher.ack(event)

# Dynamic root management (via command queue from any process):
watcher.add_root(Path("/home/user/projects"))
watcher.remove_root(Path("/home/user/docs"))

# Graceful shutdown
watcher.stop()
```

---

## Dependencies

```
watchdog>=3.0.0    # Cross-platform file system monitoring
```

---

## Future Considerations

1. **Inode-based move tracking** - More reliable than filename matching
2. **Batch event emission** - Group events for efficiency
3. **Checkpointing** - Snapshot current file state for cold start sync
4. **Remote queue backend** - Redis/RabbitMQ for distributed consumers
5. **File content hashing** - Detect false UPDATEs (touch without content change)
