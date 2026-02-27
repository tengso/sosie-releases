"""File system watcher using watchdog library."""

import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
)

from .models import RawFSEvent
from .config import WatcherConfig


class FSEventHandler(FileSystemEventHandler):
    """Handler that converts watchdog events to RawFSEvent."""

    def __init__(
        self,
        callback: Callable[[RawFSEvent], None],
        config: WatcherConfig,
        root: Path,
    ):
        super().__init__()
        self.callback = callback
        self.config = config
        self.root = root

    def _should_ignore(self, path: str) -> bool:
        """Check if the path should be ignored."""
        return self.config.should_ignore(Path(path))

    def _emit(self, event_type: str, src_path: Path, dest_path: Optional[Path] = None, is_directory: bool = False):
        """Emit a RawFSEvent to the callback."""
        if self._should_ignore(str(src_path)):
            return
        if dest_path and self._should_ignore(str(dest_path)):
            return
        
        raw_event = RawFSEvent(
            event_type=event_type,
            src_path=src_path,
            dest_path=dest_path,
            is_directory=is_directory,
            timestamp=time.time(),
        )
        self.callback(raw_event)

    def on_created(self, event):
        is_dir = isinstance(event, DirCreatedEvent)
        self._emit("created", Path(event.src_path), is_directory=is_dir)

    def on_deleted(self, event):
        is_dir = isinstance(event, DirDeletedEvent)
        self._emit("deleted", Path(event.src_path), is_directory=is_dir)

    def on_modified(self, event):
        is_dir = isinstance(event, DirModifiedEvent)
        self._emit("modified", Path(event.src_path), is_directory=is_dir)

    def on_moved(self, event):
        is_dir = isinstance(event, DirMovedEvent)
        self._emit(
            "moved",
            Path(event.src_path),
            Path(event.dest_path),
            is_directory=is_dir,
        )


class FSWatcherPool:
    """
    Manages multiple watchdog observers, one per root.
    
    Provides a unified interface for starting and stopping
    watchers for multiple root directories.
    """

    def __init__(
        self,
        event_callback: Callable[[RawFSEvent], None],
        config: Optional[WatcherConfig] = None,
    ):
        """
        Initialize the watcher pool.
        
        Args:
            event_callback: Callback function for raw filesystem events
            config: Watcher configuration
        """
        self.event_callback = event_callback
        self.config = config or WatcherConfig()
        self._observers: Dict[Path, Observer] = {}
        self._handlers: Dict[Path, FSEventHandler] = {}
        self._lock = threading.Lock()

    def start_watching(self, root: Path) -> bool:
        """
        Start watching a root directory.
        
        Args:
            root: Path to the root directory
            
        Returns:
            True if watching started, False if already watching
        """
        root = root.resolve()
        
        with self._lock:
            if root in self._observers:
                return False
            
            observer = Observer()
            handler = FSEventHandler(self.event_callback, self.config, root)
            
            observer.schedule(
                handler,
                str(root),
                recursive=self.config.recursive,
            )
            observer.start()
            
            self._observers[root] = observer
            self._handlers[root] = handler
            return True

    def stop_watching(self, root: Path) -> bool:
        """
        Stop watching a root directory.
        
        Args:
            root: Path to the root directory
            
        Returns:
            True if watching stopped, False if not watching
        """
        root = root.resolve()
        
        with self._lock:
            if root not in self._observers:
                return False
            
            observer = self._observers.pop(root)
            self._handlers.pop(root, None)
            
            observer.stop()
            observer.join(timeout=5.0)
            return True

    def stop_all(self) -> int:
        """
        Stop all watchers.
        
        Returns:
            Number of watchers stopped
        """
        with self._lock:
            count = len(self._observers)
            
            for observer in self._observers.values():
                observer.stop()
            
            for observer in self._observers.values():
                observer.join(timeout=5.0)
            
            self._observers.clear()
            self._handlers.clear()
            return count

    def is_watching(self, root: Path) -> bool:
        """
        Check if a root is being watched.
        
        Args:
            root: Path to check
            
        Returns:
            True if the root is being watched
        """
        root = root.resolve()
        
        with self._lock:
            return root in self._observers

    def get_watched_roots(self) -> list:
        """
        Get list of currently watched roots.
        
        Returns:
            List of watched root paths
        """
        with self._lock:
            return list(self._observers.keys())

    def __len__(self) -> int:
        """Return the number of active watchers."""
        with self._lock:
            return len(self._observers)
