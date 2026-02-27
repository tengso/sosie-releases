"""Event processing with move detection, deduplication, hashing, and batching."""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .config import WatcherConfig
from .models import EventType, FileEvent, RawFSEvent, EventBatch, compute_file_hash
from .root_manager import RootManager


@dataclass
class PendingEvent:
    """An event waiting to be emitted after debounce window."""
    event_type: EventType
    path: Path
    root: Path
    old_path: Optional[Path] = None
    old_root: Optional[Path] = None
    is_directory: bool = False
    timestamp: float = field(default_factory=time.time)
    content_hash: Optional[str] = None


class MoveCorrelator:
    """
    Correlates DELETE + ADD events to detect moves.
    
    Uses a time window to match delete events with subsequent
    create events that have the same filename.
    """

    def __init__(self, correlation_window_ms: int = 100):
        """
        Initialize the move correlator.
        
        Args:
            correlation_window_ms: Time window in ms to correlate events
        """
        self.correlation_window_ms = correlation_window_ms
        self._pending_deletes: Dict[str, List[Tuple[Path, float, bool]]] = defaultdict(list)
        self._lock = threading.Lock()

    def on_delete(self, path: Path, timestamp: float, is_directory: bool) -> bool:
        """
        Record a delete event for potential move correlation.
        
        Args:
            path: Path that was deleted
            timestamp: When the delete occurred
            is_directory: Whether this is a directory
            
        Returns:
            True (delete is always deferred for correlation)
        """
        filename = path.name
        
        with self._lock:
            self._pending_deletes[filename].append((path, timestamp, is_directory))
        
        return True

    def on_create(
        self,
        path: Path,
        timestamp: float,
        is_directory: bool,
    ) -> Tuple[bool, Optional[Path]]:
        """
        Check if a create event matches a pending delete (indicating a move).
        
        Args:
            path: Path that was created
            timestamp: When the create occurred
            is_directory: Whether this is a directory
            
        Returns:
            (is_move, old_path) - is_move is True if this is a move,
            old_path is the source path of the move
        """
        filename = path.name
        window_sec = self.correlation_window_ms / 1000.0
        
        with self._lock:
            if filename not in self._pending_deletes:
                return False, None
            
            pending = self._pending_deletes[filename]
            for i, (old_path, delete_time, was_dir) in enumerate(pending):
                if was_dir == is_directory and (timestamp - delete_time) < window_sec:
                    pending.pop(i)
                    if not pending:
                        del self._pending_deletes[filename]
                    return True, old_path
            
            return False, None

    def flush_expired(self, current_time: float) -> List[Tuple[Path, bool]]:
        """
        Get and remove delete events that have expired (no matching create).
        
        Args:
            current_time: Current timestamp
            
        Returns:
            List of (path, is_directory) tuples for expired deletes
        """
        window_sec = self.correlation_window_ms / 1000.0
        expired = []
        
        with self._lock:
            to_remove = []
            
            for filename, pending in self._pending_deletes.items():
                still_pending = []
                for path, delete_time, is_dir in pending:
                    if (current_time - delete_time) >= window_sec:
                        expired.append((path, is_dir))
                    else:
                        still_pending.append((path, delete_time, is_dir))
                
                if still_pending:
                    self._pending_deletes[filename] = still_pending
                else:
                    to_remove.append(filename)
            
            for filename in to_remove:
                del self._pending_deletes[filename]
        
        return expired

    def clear(self) -> None:
        """Clear all pending deletes."""
        with self._lock:
            self._pending_deletes.clear()


class EventDebouncer:
    """
    Debounces rapid file change events.
    
    Coalesces multiple events on the same path within a time window
    according to semantic rules.
    """

    def __init__(self, debounce_ms: int = 50):
        """
        Initialize the debouncer.
        
        Args:
            debounce_ms: Debounce window in milliseconds
        """
        self.debounce_ms = debounce_ms
        self._pending: Dict[Path, PendingEvent] = {}
        self._lock = threading.Lock()

    def add(self, event: PendingEvent) -> None:
        """
        Add an event to the debouncer.
        
        Coalescing rules:
        - Multiple UPDATEs → single UPDATE (latest timestamp)
        - ADD then UPDATE → single ADD
        - ADD then DELETE → cancel out (no event)
        - DELETE then ADD → UPDATE (file replaced)
        - MOVE overwrites previous events on dest path
        
        Args:
            event: The pending event to add
        """
        with self._lock:
            path = event.path
            
            # Handle MOVE specially - always remove old_path from pending
            if event.event_type == EventType.MOVE:
                self._pending[path] = event
                if event.old_path and event.old_path in self._pending:
                    del self._pending[event.old_path]
                return
            
            if path not in self._pending:
                self._pending[path] = event
                return
            
            existing = self._pending[path]
            
            if event.event_type == EventType.UPDATE:
                if existing.event_type == EventType.ADD:
                    existing.timestamp = event.timestamp
                elif existing.event_type == EventType.UPDATE:
                    existing.timestamp = event.timestamp
                    existing.content_hash = event.content_hash
            
            elif event.event_type == EventType.DELETE:
                if existing.event_type == EventType.ADD:
                    del self._pending[path]
                else:
                    self._pending[path] = event
            
            elif event.event_type == EventType.ADD:
                if existing.event_type == EventType.DELETE:
                    self._pending[path] = PendingEvent(
                        event_type=EventType.UPDATE,
                        path=path,
                        root=event.root,
                        is_directory=event.is_directory,
                        timestamp=event.timestamp,
                        content_hash=event.content_hash,
                    )
                else:
                    self._pending[path] = event

    def flush(self, current_time: float) -> List[PendingEvent]:
        """
        Flush events older than the debounce window.
        
        Args:
            current_time: Current timestamp
            
        Returns:
            List of events ready to emit
        """
        window_sec = self.debounce_ms / 1000.0
        ready = []
        
        with self._lock:
            to_remove = []
            
            for path, event in self._pending.items():
                if (current_time - event.timestamp) >= window_sec:
                    ready.append(event)
                    to_remove.append(path)
            
            for path in to_remove:
                del self._pending[path]
        
        return ready

    def flush_all(self) -> List[PendingEvent]:
        """
        Flush all pending events regardless of time.
        
        Returns:
            List of all pending events
        """
        with self._lock:
            events = list(self._pending.values())
            self._pending.clear()
            return events

    def clear(self) -> None:
        """Clear all pending events."""
        with self._lock:
            self._pending.clear()


class EventBatcher:
    """
    Batches events for efficient emission.
    
    Collects events until batch size is reached or timeout expires.
    """

    def __init__(
        self,
        batch_size: int = 100,
        batch_timeout_ms: int = 500,
        on_batch_ready: Optional[Callable[[EventBatch], None]] = None,
    ):
        """
        Initialize the batcher.
        
        Args:
            batch_size: Maximum events per batch
            batch_timeout_ms: Max time to wait before emitting partial batch
            on_batch_ready: Callback when a batch is ready
        """
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.on_batch_ready = on_batch_ready
        self._events: List[FileEvent] = []
        self._batch_start_time: Optional[float] = None
        self._lock = threading.Lock()

    def add(self, event: FileEvent) -> Optional[EventBatch]:
        """
        Add an event to the current batch.
        
        Args:
            event: The event to add
            
        Returns:
            A batch if one is ready, None otherwise
        """
        with self._lock:
            if self._batch_start_time is None:
                self._batch_start_time = time.time()
            
            self._events.append(event)
            
            if len(self._events) >= self.batch_size:
                return self._emit_batch()
            
            return None

    def add_multiple(self, events: List[FileEvent]) -> List[EventBatch]:
        """
        Add multiple events, returning any complete batches.
        
        Args:
            events: List of events to add
            
        Returns:
            List of ready batches
        """
        batches = []
        
        with self._lock:
            for event in events:
                if self._batch_start_time is None:
                    self._batch_start_time = time.time()
                
                self._events.append(event)
                
                if len(self._events) >= self.batch_size:
                    batch = self._emit_batch()
                    if batch:
                        batches.append(batch)
        
        return batches

    def check_timeout(self, current_time: float) -> Optional[EventBatch]:
        """
        Check if the current batch should be emitted due to timeout.
        
        Args:
            current_time: Current timestamp
            
        Returns:
            A batch if timeout reached, None otherwise
        """
        timeout_sec = self.batch_timeout_ms / 1000.0
        
        with self._lock:
            if not self._events:
                return None
            
            if self._batch_start_time is None:
                return None
            
            if (current_time - self._batch_start_time) >= timeout_sec:
                return self._emit_batch()
            
            return None

    def flush(self) -> Optional[EventBatch]:
        """
        Force emit the current batch regardless of size or timeout.
        
        Returns:
            The current batch, or None if empty
        """
        with self._lock:
            return self._emit_batch()

    def _emit_batch(self) -> Optional[EventBatch]:
        """Internal: create and emit a batch from current events."""
        if not self._events:
            return None
        
        batch = EventBatch(events=list(self._events))
        self._events.clear()
        self._batch_start_time = None
        
        if self.on_batch_ready:
            self.on_batch_ready(batch)
        
        return batch

    def pending_count(self) -> int:
        """Get number of events waiting in current batch."""
        with self._lock:
            return len(self._events)

    def clear(self) -> None:
        """Clear all pending events without emitting."""
        with self._lock:
            self._events.clear()
            self._batch_start_time = None


class EventProcessor:
    """
    Main event processor that transforms raw FS events into FileEvents.
    
    Handles move detection, deduplication, content hashing, and batching.
    """

    def __init__(
        self,
        root_manager: RootManager,
        config: Optional[WatcherConfig] = None,
        on_batch_ready: Optional[Callable[[EventBatch], None]] = None,
    ):
        """
        Initialize the event processor.
        
        Args:
            root_manager: Manager for watched roots
            config: Watcher configuration
            on_batch_ready: Callback when a batch of events is ready
        """
        self.root_manager = root_manager
        self.config = config or WatcherConfig()
        self.on_batch_ready = on_batch_ready
        
        self._move_correlator = MoveCorrelator(self.config.move_correlation_ms)
        self._debouncer = EventDebouncer(self.config.debounce_ms)
        self._batcher = EventBatcher(
            self.config.batch_size,
            self.config.batch_timeout_ms,
            on_batch_ready,
        )
        self._lock = threading.Lock()

    def process(self, raw_event: RawFSEvent) -> None:
        """
        Process a raw filesystem event.
        
        Args:
            raw_event: The raw event from the filesystem watcher
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"EventProcessor.process: {raw_event.event_type} - {raw_event.src_path}")
        
        with self._lock:
            if raw_event.event_type == "moved":
                self._handle_move(raw_event)
            elif raw_event.event_type == "deleted":
                self._handle_delete(raw_event)
            elif raw_event.event_type == "created":
                self._handle_create(raw_event)
            elif raw_event.event_type == "modified":
                self._handle_modify(raw_event)

    def _handle_move(self, raw_event: RawFSEvent) -> None:
        """Handle a move event from watchdog."""
        src_path = raw_event.src_path.resolve()
        dest_path = raw_event.dest_path.resolve() if raw_event.dest_path else None
        
        if dest_path is None:
            return
        
        src_root = self.root_manager.find_root_for_path(src_path)
        dest_root = self.root_manager.find_root_for_path(dest_path)
        
        content_hash = None
        if self.config.compute_hashes and not raw_event.is_directory:
            content_hash = compute_file_hash(dest_path, self.config.hash_algorithm)
        
        if src_root and dest_root:
            event = PendingEvent(
                event_type=EventType.MOVE,
                path=dest_path,
                root=dest_root,
                old_path=src_path,
                old_root=src_root,
                is_directory=raw_event.is_directory,
                timestamp=raw_event.timestamp,
                content_hash=content_hash,
            )
            self._debouncer.add(event)
        elif src_root and not dest_root:
            event = PendingEvent(
                event_type=EventType.DELETE,
                path=src_path,
                root=src_root,
                is_directory=raw_event.is_directory,
                timestamp=raw_event.timestamp,
            )
            self._debouncer.add(event)
        elif not src_root and dest_root:
            event = PendingEvent(
                event_type=EventType.ADD,
                path=dest_path,
                root=dest_root,
                is_directory=raw_event.is_directory,
                timestamp=raw_event.timestamp,
                content_hash=content_hash,
            )
            self._debouncer.add(event)

    def _handle_delete(self, raw_event: RawFSEvent) -> None:
        """Handle a delete event."""
        path = raw_event.src_path.resolve()
        self._move_correlator.on_delete(path, raw_event.timestamp, raw_event.is_directory)

    def _handle_create(self, raw_event: RawFSEvent) -> None:
        """Handle a create event."""
        path = raw_event.src_path.resolve()
        root = self.root_manager.find_root_for_path(path)
        
        if root is None:
            return
        
        is_move, old_path = self._move_correlator.on_create(
            path, raw_event.timestamp, raw_event.is_directory
        )
        
        content_hash = None
        if self.config.compute_hashes and not raw_event.is_directory:
            content_hash = compute_file_hash(path, self.config.hash_algorithm)
        
        if is_move and old_path:
            old_root = self.root_manager.find_root_for_path(old_path)
            
            if old_root:
                event = PendingEvent(
                    event_type=EventType.MOVE,
                    path=path,
                    root=root,
                    old_path=old_path,
                    old_root=old_root,
                    is_directory=raw_event.is_directory,
                    timestamp=raw_event.timestamp,
                    content_hash=content_hash,
                )
            else:
                event = PendingEvent(
                    event_type=EventType.ADD,
                    path=path,
                    root=root,
                    is_directory=raw_event.is_directory,
                    timestamp=raw_event.timestamp,
                    content_hash=content_hash,
                )
        else:
            event = PendingEvent(
                event_type=EventType.ADD,
                path=path,
                root=root,
                is_directory=raw_event.is_directory,
                timestamp=raw_event.timestamp,
                content_hash=content_hash,
            )
        
        self._debouncer.add(event)

    def _handle_modify(self, raw_event: RawFSEvent) -> None:
        """Handle a modify event."""
        path = raw_event.src_path.resolve()
        root = self.root_manager.find_root_for_path(path)
        
        if root is None:
            return
        
        content_hash = None
        if self.config.compute_hashes and not raw_event.is_directory:
            content_hash = compute_file_hash(path, self.config.hash_algorithm)
        
        event = PendingEvent(
            event_type=EventType.UPDATE,
            path=path,
            root=root,
            is_directory=raw_event.is_directory,
            timestamp=raw_event.timestamp,
            content_hash=content_hash,
        )
        self._debouncer.add(event)

    def flush(self) -> List[EventBatch]:
        """
        Flush all pending events.
        
        Processes expired move correlations, flushes debounced events,
        and emits any complete batches.
        
        Returns:
            List of event batches ready for emission
        """
        current_time = time.time()
        batches = []
        
        with self._lock:
            expired_deletes = self._move_correlator.flush_expired(current_time)
            for path, is_directory in expired_deletes:
                root = self.root_manager.find_root_for_path(path)
                if root:
                    event = PendingEvent(
                        event_type=EventType.DELETE,
                        path=path,
                        root=root,
                        is_directory=is_directory,
                        timestamp=current_time,
                    )
                    self._debouncer.add(event)
            
            ready_events = self._debouncer.flush(current_time)
            
            for pending in ready_events:
                file_event = FileEvent(
                    event_type=pending.event_type,
                    path=pending.path,
                    root=pending.root,
                    old_path=pending.old_path,
                    old_root=pending.old_root,
                    content_hash=pending.content_hash,
                    is_directory=pending.is_directory,
                    timestamp=pending.timestamp,
                )
                batch = self._batcher.add(file_event)
                if batch:
                    batches.append(batch)
            
            timeout_batch = self._batcher.check_timeout(current_time)
            if timeout_batch:
                batches.append(timeout_batch)
        
        return batches

    def flush_all(self) -> List[EventBatch]:
        """
        Force flush all pending events immediately.
        
        Returns:
            List of all event batches
        """
        current_time = time.time()
        batches = []
        
        with self._lock:
            expired_deletes = self._move_correlator.flush_expired(current_time + 1000)
            self._move_correlator.clear()
            
            for path, is_directory in expired_deletes:
                root = self.root_manager.find_root_for_path(path)
                if root:
                    event = PendingEvent(
                        event_type=EventType.DELETE,
                        path=path,
                        root=root,
                        is_directory=is_directory,
                        timestamp=current_time,
                    )
                    self._debouncer.add(event)
            
            all_events = self._debouncer.flush_all()
            
            for pending in all_events:
                file_event = FileEvent(
                    event_type=pending.event_type,
                    path=pending.path,
                    root=pending.root,
                    old_path=pending.old_path,
                    old_root=pending.old_root,
                    content_hash=pending.content_hash,
                    is_directory=pending.is_directory,
                    timestamp=pending.timestamp,
                )
                self._batcher.add(file_event)
            
            final_batch = self._batcher.flush()
            if final_batch:
                batches.append(final_batch)
        
        return batches

    def clear(self) -> None:
        """Clear all pending state."""
        with self._lock:
            self._move_correlator.clear()
            self._debouncer.clear()
            self._batcher.clear()
