"""Main watcher process orchestrator."""

import json
import threading
import time
from pathlib import Path
from typing import Iterator, List, Optional

from .config import WatcherConfig
from .exceptions import (
    WatcherError,
    WatcherNotRunningError,
    WatcherAlreadyRunningError,
)
from .models import (
    CommandType,
    EventBatch,
    EventType,
    FileEvent,
    WatcherCommand,
)
from .queue import PersistentQueue
from .root_manager import RootManager
from .fs_watcher import FSWatcherPool
from .event_processor import EventProcessor


class WatcherProcess:
    """
    Main orchestrator for the file watcher process.
    
    Coordinates root management, filesystem watching, event processing,
    and persistent queues for commands and events.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        config: Optional[WatcherConfig] = None,
        initial_roots: Optional[List[Path]] = None,
    ):
        """
        Initialize the watcher process.
        
        Args:
            db_path: Path to SQLite database (overrides config.db_path)
            config: Watcher configuration
            initial_roots: Initial root folders to watch
        """
        self.config = config or WatcherConfig()
        if db_path:
            self.config.db_path = db_path
        
        self._root_manager = RootManager()
        self._command_queue = PersistentQueue(self.config.db_path, "commands")
        self._event_queue = PersistentQueue(self.config.db_path, "events")
        
        # Initialize roots table
        self._init_roots_table()
        
        self._event_processor = EventProcessor(
            self._root_manager,
            self.config,
            self._on_batch_ready,
        )
        
        self._fs_watcher_pool = FSWatcherPool(
            self._event_processor.process,
            self.config,
        )
        
        self._running = False
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()
        
        self._command_queue.requeue_unacked()
        self._event_queue.requeue_unacked()
        
        # Load persisted roots
        self._load_persisted_roots()
        
        if initial_roots:
            for root in initial_roots:
                self._add_root_internal(root)

    def _on_batch_ready(self, batch: EventBatch) -> None:
        """Callback when a batch of events is ready."""
        self._event_queue.enqueue(batch.to_dict())

    def _init_roots_table(self) -> None:
        """Initialize the roots table and status table in the database."""
        import sqlite3
        conn = sqlite3.connect(str(self.config.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS roots (
                path TEXT PRIMARY KEY,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watcher_status (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _set_running_status(self, running: bool) -> None:
        """Set the running status in the database."""
        import sqlite3
        conn = sqlite3.connect(str(self.config.db_path))
        conn.execute(
            "INSERT OR REPLACE INTO watcher_status (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            ("running", "1" if running else "0")
        )
        conn.commit()
        conn.close()

    @staticmethod
    def check_running(db_path: Path) -> bool:
        """Check if a watcher is running for the given database."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT value FROM watcher_status WHERE key = 'running'")
            row = cursor.fetchone()
            conn.close()
            return row is not None and row[0] == "1"
        except Exception:
            return False

    def _load_persisted_roots(self) -> None:
        """Load roots from the database into the root manager and start watching."""
        import logging
        logger = logging.getLogger(__name__)
        import sqlite3
        conn = sqlite3.connect(str(self.config.db_path))
        cursor = conn.execute("SELECT path FROM roots")
        for row in cursor:
            try:
                root = Path(row[0])
                if root.exists():
                    self._root_manager.add_root(root)
                    # Also start watchdog observer for this root
                    self._fs_watcher_pool.start_watching(root)
                    logger.info(f"Started watching persisted root: {root}")
            except Exception as e:
                logger.error(f"Failed to load root {row[0]}: {e}")
        conn.close()

    def _save_root(self, root: Path) -> None:
        """Save a root to the database."""
        import sqlite3
        conn = sqlite3.connect(str(self.config.db_path))
        conn.execute(
            "INSERT OR REPLACE INTO roots (path) VALUES (?)",
            (str(root),)
        )
        conn.commit()
        conn.close()

    def _remove_persisted_root(self, root: Path) -> None:
        """Remove a root from the database."""
        import sqlite3
        conn = sqlite3.connect(str(self.config.db_path))
        conn.execute("DELETE FROM roots WHERE path = ?", (str(root),))
        conn.commit()
        conn.close()

    def _add_root_internal(self, root: Path) -> bool:
        """Internal method to add a root without queuing a command.
        
        Note: Database persistence is handled by IndexerProcess.add_root().
        The watcher only manages in-memory state and file system observers.
        """
        import logging
        from .exceptions import RootAlreadyExistsError
        logger = logging.getLogger(__name__)
        try:
            root = root.resolve()
            self._root_manager.add_root(root)
            # Don't save to database here - IndexerProcess.add_root() already did that
            self._fs_watcher_pool.start_watching(root)
            
            # Emit ROOT_ADDED event so indexer can scan the new root
            event = FileEvent(
                event_type=EventType.ROOT_ADDED,
                path=root,
                root=root,
                is_directory=True,
            )
            batch = EventBatch(events=[event])
            self._event_queue.enqueue(batch.to_dict())
            logger.info(f"Enqueued ROOT_ADDED event for: {root}")
            
            return True
        except RootAlreadyExistsError:
            logger.debug(f"Root already being watched: {root}")
            return True  # Not an error - root is already watched
        except Exception as e:
            logger.error(f"Error adding root {root}: {e}")
            return False

    def _remove_root_internal(self, root: Path) -> bool:
        """Internal method to remove a root without queuing a command.
        
        Note: Database cleanup is handled by IndexerProcess.remove_root().
        The watcher only manages in-memory state and file system observers.
        """
        try:
            root = root.resolve()
            self._fs_watcher_pool.stop_watching(root)
            self._root_manager.remove_root(root)
            # Don't delete from database here - IndexerProcess.remove_root() already did that
            
            # Emit ROOT_REMOVED event so indexer can remove files under this root
            event = FileEvent(
                event_type=EventType.ROOT_REMOVED,
                path=root,
                root=root,
                is_directory=True,
            )
            batch = EventBatch(events=[event])
            self._event_queue.enqueue(batch.to_dict())
            
            return True
        except Exception:
            return False

    def add_root(self, root: Path) -> None:
        """
        Add a root folder to watch.
        
        This queues a command that will be processed by the watcher.
        
        Args:
            root: Path to the root folder
        """
        command = WatcherCommand(CommandType.ADD_ROOT, root.resolve())
        self._command_queue.enqueue(command.to_dict())

    def remove_root(self, root: Path) -> None:
        """
        Remove a root folder from watching.
        
        This queues a command that will be processed by the watcher.
        
        Args:
            root: Path to the root folder
        """
        command = WatcherCommand(CommandType.REMOVE_ROOT, root.resolve())
        self._command_queue.enqueue(command.to_dict())

    def resync(self) -> None:
        """
        Trigger a full resync of all watched roots.
        
        This queues a command that will be processed by the watcher.
        """
        command = WatcherCommand(CommandType.RESYNC)
        self._command_queue.enqueue(command.to_dict())

    def _resync_internal(self) -> None:
        """Internal method to trigger resync event for indexer."""
        import logging
        logger = logging.getLogger(__name__)
        
        roots = self.get_roots()
        logger.info(f"Triggering resync for {len(roots)} root(s)")
        
        # Emit RESYNC event so indexer can do a full sync
        event = FileEvent(
            event_type=EventType.RESYNC,
            path=Path("/"),  # Placeholder path
            root=Path("/"),
            is_directory=True,
        )
        batch = EventBatch(events=[event])
        self._event_queue.enqueue(batch.to_dict())
        logger.info("Enqueued RESYNC event")

    def integrity_check(self) -> None:
        """
        Trigger an integrity check of indexed files vs watched files.
        
        This queues a command that will be processed by the watcher.
        """
        command = WatcherCommand(CommandType.INTEGRITY_CHECK)
        self._command_queue.enqueue(command.to_dict())

    def _integrity_check_internal(self) -> None:
        """Internal method to trigger integrity check event for indexer."""
        import logging
        logger = logging.getLogger(__name__)
        
        roots = self.get_roots()
        logger.info(f"Triggering integrity check for {len(roots)} root(s)")
        
        # Emit INTEGRITY_CHECK event so indexer can report status
        event = FileEvent(
            event_type=EventType.INTEGRITY_CHECK,
            path=Path("/"),  # Placeholder path
            root=Path("/"),
            is_directory=True,
        )
        batch = EventBatch(events=[event])
        self._event_queue.enqueue(batch.to_dict())
        logger.info("Enqueued INTEGRITY_CHECK event")

    def get_roots(self) -> List[Path]:
        """
        Get the current list of watched roots.
        
        Returns:
            List of root paths
        """
        return list(self._root_manager.get_roots())

    def start(self) -> None:
        """
        Start the watcher process (blocking).
        
        This starts all worker threads and blocks until stop() is called.
        
        Raises:
            WatcherAlreadyRunningError: If already running
        """
        with self._lock:
            if self._running:
                raise WatcherAlreadyRunningError("Watcher is already running")
            
            self._running = True
            self._stop_event.clear()
        
        self._threads = [
            threading.Thread(target=self._command_consumer_loop, name="CommandConsumer"),
            threading.Thread(target=self._flush_loop, name="FlushLoop"),
        ]
        
        for thread in self._threads:
            thread.daemon = True
            thread.start()
        
        # Mark as running in database
        self._set_running_status(True)
        
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def start_async(self) -> None:
        """
        Start the watcher process in the background.
        
        Returns immediately while the watcher runs in background threads.
        
        Raises:
            WatcherAlreadyRunningError: If already running
        """
        with self._lock:
            if self._running:
                raise WatcherAlreadyRunningError("Watcher is already running")
            
            self._running = True
            self._stop_event.clear()
        
        self._threads = [
            threading.Thread(target=self._command_consumer_loop, name="CommandConsumer"),
            threading.Thread(target=self._flush_loop, name="FlushLoop"),
        ]
        
        # Mark as running in database
        self._set_running_status(True)
        
        for thread in self._threads:
            thread.daemon = True
            thread.start()

    def stop(self) -> None:
        """
        Stop the watcher process gracefully.
        
        Signals all threads to stop and waits for them to finish.
        """
        self._stop_event.set()
        self._shutdown()

    def _shutdown(self) -> None:
        """Internal shutdown procedure."""
        with self._lock:
            if not self._running:
                return
            
            self._running = False
        
        # Mark as not running in database
        self._set_running_status(False)
        
        for batch in self._event_processor.flush_all():
            self._event_queue.enqueue(batch.to_dict())
        
        self._fs_watcher_pool.stop_all()
        
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        
        self._threads.clear()

    def _command_consumer_loop(self) -> None:
        """Worker loop that processes commands from the command queue."""
        import logging
        logger = logging.getLogger(__name__)
        logger.debug("Command consumer loop started")
        
        while not self._stop_event.is_set():
            try:
                items = self._command_queue.dequeue(batch_size=10)
                
                if not items:
                    time.sleep(0.1)
                    continue
                
                ids_to_ack = []
                
                for item_id, item_data in items:
                    try:
                        command = WatcherCommand.from_dict(item_data)
                        logger.info(f"Processing command: {command.command_type.value} - {command.root}")
                        self._process_command(command)
                        ids_to_ack.append(item_id)
                    except Exception as e:
                        logger.error(f"Error processing command: {e}")
                        ids_to_ack.append(item_id)
                
                if ids_to_ack:
                    self._command_queue.ack(ids_to_ack)
                    
            except Exception:
                time.sleep(0.5)

    def _process_command(self, command: WatcherCommand) -> None:
        """Process a single command."""
        if command.command_type == CommandType.ADD_ROOT:
            if command.root:
                self._add_root_internal(command.root)
        elif command.command_type == CommandType.REMOVE_ROOT:
            if command.root:
                self._remove_root_internal(command.root)
        elif command.command_type == CommandType.RESYNC:
            self._resync_internal()
        elif command.command_type == CommandType.INTEGRITY_CHECK:
            self._integrity_check_internal()
        elif command.command_type == CommandType.SHUTDOWN:
            self._stop_event.set()

    def _flush_loop(self) -> None:
        """Worker loop that periodically flushes pending events."""
        import logging
        logger = logging.getLogger(__name__)
        
        flush_interval = self.config.flush_interval_ms / 1000.0
        logger.debug(f"Flush loop started, interval={flush_interval}s")
        
        while not self._stop_event.is_set():
            try:
                batches = self._event_processor.flush()
                for batch in batches:
                    logger.debug(f"Enqueuing batch with {len(batch.events)} events")
                    self._event_queue.enqueue(batch.to_dict())
            except Exception as e:
                logger.error(f"Flush loop error: {e}")
            
            self._stop_event.wait(timeout=flush_interval)

    def iter_events(self, batch_size: int = 1) -> Iterator[FileEvent]:
        """
        Iterate over file events from the event queue.
        
        This is a blocking iterator that yields events as they become
        available. Each event must be acknowledged after processing.
        
        Args:
            batch_size: Number of events to fetch at a time
            
        Yields:
            FileEvent objects
        """
        while True:
            items = self._event_queue.dequeue(batch_size=1)
            
            if not items:
                time.sleep(0.1)
                continue
            
            for item_id, item_data in items:
                try:
                    batch = EventBatch.from_dict(item_data)
                    for event in batch.events:
                        yield event
                    self._event_queue.ack([item_id])
                except Exception:
                    self._event_queue.ack([item_id])

    def iter_batches(self) -> Iterator[EventBatch]:
        """
        Iterate over event batches from the event queue.
        
        This is a blocking iterator that yields batches as they become
        available.
        
        Yields:
            EventBatch objects
        """
        while True:
            items = self._event_queue.dequeue(batch_size=1)
            
            if not items:
                time.sleep(0.1)
                continue
            
            for item_id, item_data in items:
                try:
                    batch = EventBatch.from_dict(item_data)
                    yield batch
                    self._event_queue.ack([item_id])
                except Exception:
                    self._event_queue.ack([item_id])

    def get_pending_events(self, max_count: int = 100) -> List[FileEvent]:
        """
        Get pending events without blocking.
        
        Args:
            max_count: Maximum number of events to return
            
        Returns:
            List of pending file events
        """
        events = []
        items = self._event_queue.dequeue(batch_size=max_count)
        
        ids_to_ack = []
        for item_id, item_data in items:
            try:
                batch = EventBatch.from_dict(item_data)
                events.extend(batch.events)
                ids_to_ack.append(item_id)
            except Exception:
                ids_to_ack.append(item_id)
        
        if ids_to_ack:
            self._event_queue.ack(ids_to_ack)
        
        return events[:max_count]

    def get_pending_batches(self, max_count: int = 10) -> List[EventBatch]:
        """
        Get pending event batches without blocking.
        
        Args:
            max_count: Maximum number of batches to return
            
        Returns:
            List of pending event batches
        """
        batches = []
        items = self._event_queue.dequeue(batch_size=max_count)
        
        ids_to_ack = []
        for item_id, item_data in items:
            try:
                batch = EventBatch.from_dict(item_data)
                batches.append(batch)
                ids_to_ack.append(item_id)
            except Exception:
                ids_to_ack.append(item_id)
        
        if ids_to_ack:
            self._event_queue.ack(ids_to_ack)
        
        return batches

    def event_queue_size(self) -> int:
        """
        Get the number of pending events in the queue.
        
        Returns:
            Number of pending event batches
        """
        return self._event_queue.size()

    def command_queue_size(self) -> int:
        """
        Get the number of pending commands in the queue.
        
        Returns:
            Number of pending commands
        """
        return self._command_queue.size()

    @property
    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._running

    def close(self) -> None:
        """Close the watcher and release all resources."""
        self.stop()
        self._command_queue.close()
        self._event_queue.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
