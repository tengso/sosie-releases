"""
File Watcher Package

A file watcher process that monitors root folders for file system changes
and produces structured events via a persistent queue.

Features:
- Dynamic root folder management
- File change events: ADD, DELETE, UPDATE, MOVE
- Move detection via DELETE+ADD correlation
- Content hashing for change detection
- Batch event emission for efficiency
- Persistent queues for crash recovery
"""

from .models import (
    EventType,
    CommandType,
    FileEvent,
    WatcherCommand,
    RawFSEvent,
    EventBatch,
    compute_file_hash,
)

from .config import WatcherConfig

from .exceptions import (
    WatcherError,
    QueueError,
    QueueCorruptionError,
    RootError,
    RootNotFoundError,
    RootAlreadyExistsError,
    WatcherNotRunningError,
    WatcherAlreadyRunningError,
)

from .queue import PersistentQueue
from .root_manager import RootManager
from .fs_watcher import FSWatcherPool, FSEventHandler
from .event_processor import (
    EventProcessor,
    EventDebouncer,
    EventBatcher,
    MoveCorrelator,
)
from .process import WatcherProcess


__all__ = [
    # Models
    "EventType",
    "CommandType",
    "FileEvent",
    "WatcherCommand",
    "RawFSEvent",
    "EventBatch",
    "compute_file_hash",
    # Config
    "WatcherConfig",
    # Exceptions
    "WatcherError",
    "QueueError",
    "QueueCorruptionError",
    "RootError",
    "RootNotFoundError",
    "RootAlreadyExistsError",
    "WatcherNotRunningError",
    "WatcherAlreadyRunningError",
    # Components
    "PersistentQueue",
    "RootManager",
    "FSWatcherPool",
    "FSEventHandler",
    "EventProcessor",
    "EventDebouncer",
    "EventBatcher",
    "MoveCorrelator",
    # Main Process
    "WatcherProcess",
]

__version__ = "0.1.0"
