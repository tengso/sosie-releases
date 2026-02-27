"""Tests for models module."""

import pytest
import tempfile
import time
from pathlib import Path

from src.watcher.models import (
    EventType,
    CommandType,
    FileEvent,
    WatcherCommand,
    RawFSEvent,
    EventBatch,
    compute_file_hash,
)


class TestEventType:
    """Tests for EventType enum."""

    def test_event_type_values(self):
        assert EventType.ADD.value == "add"
        assert EventType.DELETE.value == "delete"
        assert EventType.UPDATE.value == "update"
        assert EventType.MOVE.value == "move"

    def test_event_type_from_value(self):
        assert EventType("add") == EventType.ADD
        assert EventType("delete") == EventType.DELETE
        assert EventType("update") == EventType.UPDATE
        assert EventType("move") == EventType.MOVE


class TestCommandType:
    """Tests for CommandType enum."""

    def test_command_type_values(self):
        assert CommandType.ADD_ROOT.value == "add_root"
        assert CommandType.REMOVE_ROOT.value == "remove_root"
        assert CommandType.SHUTDOWN.value == "shutdown"


class TestFileEvent:
    """Tests for FileEvent dataclass."""

    def test_create_file_event(self, tmp_path):
        event = FileEvent(
            event_type=EventType.ADD,
            path=tmp_path / "test.txt",
            root=tmp_path,
        )
        assert event.event_type == EventType.ADD
        assert event.path == tmp_path / "test.txt"
        assert event.root == tmp_path

    def test_file_event_requires_absolute_path(self):
        with pytest.raises(ValueError, match="path must be absolute"):
            FileEvent(
                event_type=EventType.ADD,
                path=Path("relative/path.txt"),
                root=Path("/absolute/root"),
            )

    def test_file_event_requires_absolute_root(self, tmp_path):
        with pytest.raises(ValueError, match="root must be absolute"):
            FileEvent(
                event_type=EventType.ADD,
                path=tmp_path / "test.txt",
                root=Path("relative/root"),
            )

    def test_file_event_requires_absolute_old_path(self, tmp_path):
        with pytest.raises(ValueError, match="old_path must be absolute"):
            FileEvent(
                event_type=EventType.MOVE,
                path=tmp_path / "new.txt",
                root=tmp_path,
                old_path=Path("relative/old.txt"),
            )

    def test_file_event_requires_absolute_old_root(self, tmp_path):
        with pytest.raises(ValueError, match="old_root must be absolute"):
            FileEvent(
                event_type=EventType.MOVE,
                path=tmp_path / "new.txt",
                root=tmp_path,
                old_path=tmp_path / "old.txt",
                old_root=Path("relative/root"),
            )

    def test_file_event_with_move(self, tmp_path):
        old_root = tmp_path / "old_root"
        new_root = tmp_path / "new_root"
        old_root.mkdir()
        new_root.mkdir()

        event = FileEvent(
            event_type=EventType.MOVE,
            path=new_root / "file.txt",
            root=new_root,
            old_path=old_root / "file.txt",
            old_root=old_root,
        )
        assert event.event_type == EventType.MOVE
        assert event.old_path == old_root / "file.txt"
        assert event.old_root == old_root

    def test_file_event_with_hash(self, tmp_path):
        event = FileEvent(
            event_type=EventType.ADD,
            path=tmp_path / "test.txt",
            root=tmp_path,
            content_hash="abc123",
        )
        assert event.content_hash == "abc123"

    def test_file_event_to_dict(self, tmp_path):
        event = FileEvent(
            event_type=EventType.ADD,
            path=tmp_path / "test.txt",
            root=tmp_path,
            content_hash="abc123",
            is_directory=False,
            timestamp=1234567890.0,
        )
        d = event.to_dict()
        assert d["event_type"] == "add"
        assert d["path"] == str(tmp_path / "test.txt")
        assert d["root"] == str(tmp_path)
        assert d["content_hash"] == "abc123"
        assert d["is_directory"] is False
        assert d["timestamp"] == 1234567890.0

    def test_file_event_from_dict(self, tmp_path):
        d = {
            "event_type": "update",
            "path": str(tmp_path / "test.txt"),
            "root": str(tmp_path),
            "old_path": None,
            "old_root": None,
            "content_hash": "xyz789",
            "is_directory": False,
            "timestamp": 1234567890.0,
        }
        event = FileEvent.from_dict(d)
        assert event.event_type == EventType.UPDATE
        assert event.path == tmp_path / "test.txt"
        assert event.content_hash == "xyz789"

    def test_file_event_roundtrip(self, tmp_path):
        original = FileEvent(
            event_type=EventType.MOVE,
            path=tmp_path / "new.txt",
            root=tmp_path,
            old_path=tmp_path / "old.txt",
            old_root=tmp_path,
            content_hash="hash123",
            is_directory=False,
            timestamp=time.time(),
        )
        restored = FileEvent.from_dict(original.to_dict())
        assert restored.event_type == original.event_type
        assert restored.path == original.path
        assert restored.root == original.root
        assert restored.old_path == original.old_path
        assert restored.old_root == original.old_root
        assert restored.content_hash == original.content_hash

    def test_file_event_frozen(self, tmp_path):
        event = FileEvent(
            event_type=EventType.ADD,
            path=tmp_path / "test.txt",
            root=tmp_path,
        )
        with pytest.raises(AttributeError):
            event.path = tmp_path / "other.txt"


class TestWatcherCommand:
    """Tests for WatcherCommand dataclass."""

    def test_create_add_root_command(self, tmp_path):
        cmd = WatcherCommand(
            command_type=CommandType.ADD_ROOT,
            root=tmp_path,
        )
        assert cmd.command_type == CommandType.ADD_ROOT
        assert cmd.root == tmp_path

    def test_create_shutdown_command(self):
        cmd = WatcherCommand(command_type=CommandType.SHUTDOWN)
        assert cmd.command_type == CommandType.SHUTDOWN
        assert cmd.root is None

    def test_command_to_dict(self, tmp_path):
        cmd = WatcherCommand(
            command_type=CommandType.ADD_ROOT,
            root=tmp_path,
            timestamp=1234567890.0,
        )
        d = cmd.to_dict()
        assert d["command_type"] == "add_root"
        assert d["root"] == str(tmp_path)
        assert d["timestamp"] == 1234567890.0

    def test_command_from_dict(self, tmp_path):
        d = {
            "command_type": "remove_root",
            "root": str(tmp_path),
            "timestamp": 1234567890.0,
        }
        cmd = WatcherCommand.from_dict(d)
        assert cmd.command_type == CommandType.REMOVE_ROOT
        assert cmd.root == tmp_path

    def test_command_roundtrip(self, tmp_path):
        original = WatcherCommand(
            command_type=CommandType.ADD_ROOT,
            root=tmp_path,
        )
        restored = WatcherCommand.from_dict(original.to_dict())
        assert restored.command_type == original.command_type
        assert restored.root == original.root


class TestRawFSEvent:
    """Tests for RawFSEvent dataclass."""

    def test_create_raw_event(self, tmp_path):
        event = RawFSEvent(
            event_type="created",
            src_path=tmp_path / "test.txt",
        )
        assert event.event_type == "created"
        assert event.src_path == tmp_path / "test.txt"
        assert event.dest_path is None
        assert event.is_directory is False

    def test_create_move_event(self, tmp_path):
        event = RawFSEvent(
            event_type="moved",
            src_path=tmp_path / "old.txt",
            dest_path=tmp_path / "new.txt",
        )
        assert event.event_type == "moved"
        assert event.dest_path == tmp_path / "new.txt"

    def test_create_directory_event(self, tmp_path):
        event = RawFSEvent(
            event_type="created",
            src_path=tmp_path / "subdir",
            is_directory=True,
        )
        assert event.is_directory is True


class TestEventBatch:
    """Tests for EventBatch dataclass."""

    def test_create_empty_batch(self):
        batch = EventBatch(events=[])
        assert len(batch) == 0
        assert batch.batch_id is not None
        assert batch.created_at > 0

    def test_create_batch_with_events(self, tmp_path):
        events = [
            FileEvent(EventType.ADD, tmp_path / "a.txt", tmp_path),
            FileEvent(EventType.UPDATE, tmp_path / "b.txt", tmp_path),
        ]
        batch = EventBatch(events=events)
        assert len(batch) == 2

    def test_batch_iteration(self, tmp_path):
        events = [
            FileEvent(EventType.ADD, tmp_path / "a.txt", tmp_path),
            FileEvent(EventType.DELETE, tmp_path / "b.txt", tmp_path),
        ]
        batch = EventBatch(events=events)
        
        iterated = list(batch)
        assert len(iterated) == 2
        assert iterated[0].event_type == EventType.ADD
        assert iterated[1].event_type == EventType.DELETE

    def test_batch_to_dict(self, tmp_path):
        events = [
            FileEvent(EventType.ADD, tmp_path / "a.txt", tmp_path),
        ]
        batch = EventBatch(events=events, batch_id="test123")
        d = batch.to_dict()
        assert d["batch_id"] == "test123"
        assert len(d["events"]) == 1

    def test_batch_from_dict(self, tmp_path):
        d = {
            "events": [
                {
                    "event_type": "add",
                    "path": str(tmp_path / "test.txt"),
                    "root": str(tmp_path),
                    "old_path": None,
                    "old_root": None,
                    "content_hash": None,
                    "is_directory": False,
                    "timestamp": time.time(),
                }
            ],
            "batch_id": "batch123",
            "created_at": time.time(),
        }
        batch = EventBatch.from_dict(d)
        assert batch.batch_id == "batch123"
        assert len(batch) == 1

    def test_batch_roundtrip(self, tmp_path):
        original = EventBatch(
            events=[
                FileEvent(EventType.ADD, tmp_path / "a.txt", tmp_path),
                FileEvent(EventType.UPDATE, tmp_path / "b.txt", tmp_path, content_hash="abc"),
            ],
            batch_id="roundtrip123",
        )
        restored = EventBatch.from_dict(original.to_dict())
        assert restored.batch_id == original.batch_id
        assert len(restored) == len(original)
        assert restored.events[1].content_hash == "abc"


class TestComputeFileHash:
    """Tests for compute_file_hash function."""

    def test_hash_simple_file(self, tmp_path):
        file = tmp_path / "test.txt"
        file.write_text("hello world")
        
        hash_result = compute_file_hash(file)
        assert hash_result is not None
        assert len(hash_result) == 64  # SHA-256 hex digest length

    def test_hash_binary_file(self, tmp_path):
        file = tmp_path / "binary.bin"
        file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd")
        
        hash_result = compute_file_hash(file)
        assert hash_result is not None

    def test_hash_large_file(self, tmp_path):
        file = tmp_path / "large.bin"
        file.write_bytes(b"x" * 1000000)  # 1MB
        
        hash_result = compute_file_hash(file)
        assert hash_result is not None

    def test_hash_nonexistent_file(self, tmp_path):
        file = tmp_path / "nonexistent.txt"
        
        hash_result = compute_file_hash(file)
        assert hash_result is None

    def test_hash_directory(self, tmp_path):
        hash_result = compute_file_hash(tmp_path)
        assert hash_result is None

    def test_hash_empty_file(self, tmp_path):
        file = tmp_path / "empty.txt"
        file.write_text("")
        
        hash_result = compute_file_hash(file)
        assert hash_result is not None
        # SHA-256 of empty string
        assert hash_result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_hash_same_content_same_hash(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = "same content"
        file1.write_text(content)
        file2.write_text(content)
        
        hash1 = compute_file_hash(file1)
        hash2 = compute_file_hash(file2)
        assert hash1 == hash2

    def test_hash_different_content_different_hash(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")
        
        hash1 = compute_file_hash(file1)
        hash2 = compute_file_hash(file2)
        assert hash1 != hash2

    def test_hash_with_md5_algorithm(self, tmp_path):
        file = tmp_path / "test.txt"
        file.write_text("hello")
        
        hash_result = compute_file_hash(file, algorithm="md5")
        assert hash_result is not None
        assert len(hash_result) == 32  # MD5 hex digest length

    def test_hash_with_sha1_algorithm(self, tmp_path):
        file = tmp_path / "test.txt"
        file.write_text("hello")
        
        hash_result = compute_file_hash(file, algorithm="sha1")
        assert hash_result is not None
        assert len(hash_result) == 40  # SHA-1 hex digest length
