"""Data models for the file watcher package."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List
import hashlib
import time


class EventType(Enum):
    """Types of file system events."""
    ADD = "add"
    DELETE = "delete"
    UPDATE = "update"
    MOVE = "move"
    ROOT_ADDED = "root_added"
    ROOT_REMOVED = "root_removed"
    RESYNC = "resync"
    INTEGRITY_CHECK = "integrity_check"


class CommandType(Enum):
    """Types of commands for the watcher process."""
    ADD_ROOT = "add_root"
    REMOVE_ROOT = "remove_root"
    RESYNC = "resync"
    INTEGRITY_CHECK = "integrity_check"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class FileEvent:
    """
    Represents a file system change event.
    
    Attributes:
        event_type: The type of event (ADD, DELETE, UPDATE, MOVE)
        path: Full absolute path to the affected file
        root: The root folder this file belongs to
        old_path: For MOVE events, the previous full path
        old_root: For cross-root MOVE events, the previous root
        content_hash: SHA-256 hash of file content (None for DELETE events)
        is_directory: Whether this event is for a directory
        timestamp: Unix timestamp when the event occurred
    """
    event_type: EventType
    path: Path
    root: Path
    old_path: Optional[Path] = None
    old_root: Optional[Path] = None
    content_hash: Optional[str] = None
    is_directory: bool = False
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.path.is_absolute():
            raise ValueError(f"path must be absolute: {self.path}")
        if not self.root.is_absolute():
            raise ValueError(f"root must be absolute: {self.root}")
        if self.old_path is not None and not self.old_path.is_absolute():
            raise ValueError(f"old_path must be absolute: {self.old_path}")
        if self.old_root is not None and not self.old_root.is_absolute():
            raise ValueError(f"old_root must be absolute: {self.old_root}")

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "event_type": self.event_type.value,
            "path": str(self.path),
            "root": str(self.root),
            "old_path": str(self.old_path) if self.old_path else None,
            "old_root": str(self.old_root) if self.old_root else None,
            "content_hash": self.content_hash,
            "is_directory": self.is_directory,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileEvent":
        """Create from dictionary."""
        return cls(
            event_type=EventType(data["event_type"]),
            path=Path(data["path"]),
            root=Path(data["root"]),
            old_path=Path(data["old_path"]) if data.get("old_path") else None,
            old_root=Path(data["old_root"]) if data.get("old_root") else None,
            content_hash=data.get("content_hash"),
            is_directory=data.get("is_directory", False),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass(frozen=True)
class WatcherCommand:
    """
    Command to control the watcher process.
    
    Attributes:
        command_type: The type of command
        root: The root path (for ADD_ROOT/REMOVE_ROOT commands)
        timestamp: Unix timestamp when the command was created
    """
    command_type: CommandType
    root: Optional[Path] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "command_type": self.command_type.value,
            "root": str(self.root) if self.root else None,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WatcherCommand":
        """Create from dictionary."""
        return cls(
            command_type=CommandType(data["command_type"]),
            root=Path(data["root"]) if data.get("root") else None,
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class RawFSEvent:
    """
    Raw event from the filesystem watcher before processing.
    
    Attributes:
        event_type: Raw event type string (created, deleted, modified, moved)
        src_path: Source path of the event
        dest_path: Destination path (for move events)
        is_directory: Whether this is a directory event
        timestamp: Unix timestamp when the event occurred
    """
    event_type: str
    src_path: Path
    dest_path: Optional[Path] = None
    is_directory: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class EventBatch:
    """
    A batch of file events for efficient processing.
    
    Attributes:
        events: List of file events in this batch
        batch_id: Unique identifier for this batch
        created_at: Unix timestamp when the batch was created
    """
    events: List[FileEvent]
    batch_id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:12])
    created_at: float = field(default_factory=time.time)

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self):
        return iter(self.events)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "events": [e.to_dict() for e in self.events],
            "batch_id": self.batch_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventBatch":
        """Create from dictionary."""
        return cls(
            events=[FileEvent.from_dict(e) for e in data["events"]],
            batch_id=data.get("batch_id", ""),
            created_at=data.get("created_at", time.time()),
        )


def compute_file_hash(path: Path, algorithm: str = "sha256") -> Optional[str]:
    """
    Compute hash of file contents.
    
    Args:
        path: Path to the file
        algorithm: Hash algorithm to use (default: sha256)
        
    Returns:
        Hex digest of the hash, or None if file cannot be read
    """
    if not path.exists() or path.is_dir():
        return None
    
    try:
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (IOError, OSError, PermissionError):
        return None
