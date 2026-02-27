"""Tests for event processor module."""

import pytest
import time
from pathlib import Path

from src.watcher.config import WatcherConfig
from src.watcher.models import EventType, RawFSEvent, FileEvent, EventBatch
from src.watcher.root_manager import RootManager
from src.watcher.event_processor import (
    EventProcessor,
    EventDebouncer,
    EventBatcher,
    MoveCorrelator,
    PendingEvent,
)


class TestMoveCorrelator:
    """Tests for MoveCorrelator class."""

    def test_on_delete_returns_true(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=100)
        result = correlator.on_delete(tmp_path / "file.txt", time.time(), False)
        assert result is True

    def test_on_create_no_pending_delete(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=100)
        is_move, old_path = correlator.on_create(tmp_path / "file.txt", time.time(), False)
        
        assert is_move is False
        assert old_path is None

    def test_on_create_matching_delete(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=100)
        now = time.time()
        
        old_path = tmp_path / "old" / "file.txt"
        new_path = tmp_path / "new" / "file.txt"
        
        correlator.on_delete(old_path, now, False)
        is_move, found_old_path = correlator.on_create(new_path, now + 0.05, False)
        
        assert is_move is True
        assert found_old_path == old_path

    def test_on_create_expired_delete(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=50)
        now = time.time()
        
        old_path = tmp_path / "old" / "file.txt"
        new_path = tmp_path / "new" / "file.txt"
        
        correlator.on_delete(old_path, now, False)
        # Create happens after correlation window
        is_move, found_old_path = correlator.on_create(new_path, now + 0.1, False)
        
        assert is_move is False
        assert found_old_path is None

    def test_on_create_different_filename(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=100)
        now = time.time()
        
        correlator.on_delete(tmp_path / "old.txt", now, False)
        is_move, old_path = correlator.on_create(tmp_path / "new.txt", now + 0.05, False)
        
        assert is_move is False
        assert old_path is None

    def test_directory_vs_file(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=100)
        now = time.time()
        
        # Delete a directory
        correlator.on_delete(tmp_path / "mydir", now, is_directory=True)
        # Create a file with same name - should not match
        is_move, old_path = correlator.on_create(tmp_path / "mydir", now + 0.05, is_directory=False)
        
        assert is_move is False

    def test_flush_expired(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=50)
        now = time.time()
        
        correlator.on_delete(tmp_path / "file1.txt", now, False)
        correlator.on_delete(tmp_path / "file2.txt", now, True)
        
        # Flush after window expires
        expired = correlator.flush_expired(now + 0.1)
        
        assert len(expired) == 2
        paths = [p for p, _ in expired]
        assert tmp_path / "file1.txt" in paths
        assert tmp_path / "file2.txt" in paths

    def test_flush_expired_partial(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=100)
        now = time.time()
        
        correlator.on_delete(tmp_path / "old.txt", now, False)
        correlator.on_delete(tmp_path / "new.txt", now + 0.15, False)
        
        # Only first delete should be expired
        expired = correlator.flush_expired(now + 0.12)
        
        assert len(expired) == 1
        assert expired[0][0] == tmp_path / "old.txt"

    def test_clear(self, tmp_path):
        correlator = MoveCorrelator(correlation_window_ms=100)
        now = time.time()
        
        correlator.on_delete(tmp_path / "file.txt", now, False)
        correlator.clear()
        
        expired = correlator.flush_expired(now + 1)
        assert len(expired) == 0


class TestEventDebouncer:
    """Tests for EventDebouncer class."""

    def test_add_single_event(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        
        event = PendingEvent(
            event_type=EventType.ADD,
            path=tmp_path / "file.txt",
            root=tmp_path,
        )
        debouncer.add(event)
        
        # Not yet expired
        ready = debouncer.flush(time.time())
        assert len(ready) == 0

    def test_flush_after_debounce(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        now = time.time()
        
        event = PendingEvent(
            event_type=EventType.ADD,
            path=tmp_path / "file.txt",
            root=tmp_path,
            timestamp=now,
        )
        debouncer.add(event)
        
        # Flush after debounce window
        ready = debouncer.flush(now + 0.1)
        assert len(ready) == 1
        assert ready[0].event_type == EventType.ADD

    def test_coalesce_multiple_updates(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        now = time.time()
        
        path = tmp_path / "file.txt"
        
        debouncer.add(PendingEvent(EventType.UPDATE, path, tmp_path, timestamp=now, content_hash="hash1"))
        debouncer.add(PendingEvent(EventType.UPDATE, path, tmp_path, timestamp=now + 0.01, content_hash="hash2"))
        debouncer.add(PendingEvent(EventType.UPDATE, path, tmp_path, timestamp=now + 0.02, content_hash="hash3"))
        
        ready = debouncer.flush(now + 0.1)
        assert len(ready) == 1
        assert ready[0].event_type == EventType.UPDATE
        assert ready[0].content_hash == "hash3"

    def test_add_then_update_becomes_add(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        now = time.time()
        
        path = tmp_path / "file.txt"
        
        debouncer.add(PendingEvent(EventType.ADD, path, tmp_path, timestamp=now))
        debouncer.add(PendingEvent(EventType.UPDATE, path, tmp_path, timestamp=now + 0.01))
        
        ready = debouncer.flush(now + 0.1)
        assert len(ready) == 1
        assert ready[0].event_type == EventType.ADD

    def test_add_then_delete_cancels(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        now = time.time()
        
        path = tmp_path / "file.txt"
        
        debouncer.add(PendingEvent(EventType.ADD, path, tmp_path, timestamp=now))
        debouncer.add(PendingEvent(EventType.DELETE, path, tmp_path, timestamp=now + 0.01))
        
        ready = debouncer.flush(now + 0.1)
        assert len(ready) == 0

    def test_delete_then_add_becomes_update(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        now = time.time()
        
        path = tmp_path / "file.txt"
        
        debouncer.add(PendingEvent(EventType.DELETE, path, tmp_path, timestamp=now))
        debouncer.add(PendingEvent(EventType.ADD, path, tmp_path, timestamp=now + 0.01, content_hash="newhash"))
        
        ready = debouncer.flush(now + 0.1)
        assert len(ready) == 1
        assert ready[0].event_type == EventType.UPDATE
        assert ready[0].content_hash == "newhash"

    def test_move_replaces_old_events(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        now = time.time()
        
        old_path = tmp_path / "old.txt"
        new_path = tmp_path / "new.txt"
        
        debouncer.add(PendingEvent(EventType.ADD, old_path, tmp_path, timestamp=now))
        debouncer.add(PendingEvent(
            EventType.MOVE, new_path, tmp_path, 
            old_path=old_path, old_root=tmp_path, timestamp=now + 0.01
        ))
        
        ready = debouncer.flush(now + 0.1)
        assert len(ready) == 1
        assert ready[0].event_type == EventType.MOVE
        assert ready[0].path == new_path

    def test_flush_all(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=1000)  # Long debounce
        now = time.time()
        
        debouncer.add(PendingEvent(EventType.ADD, tmp_path / "a.txt", tmp_path, timestamp=now))
        debouncer.add(PendingEvent(EventType.ADD, tmp_path / "b.txt", tmp_path, timestamp=now))
        
        # Force flush all regardless of time
        ready = debouncer.flush_all()
        assert len(ready) == 2

    def test_clear(self, tmp_path):
        debouncer = EventDebouncer(debounce_ms=50)
        now = time.time()
        
        debouncer.add(PendingEvent(EventType.ADD, tmp_path / "file.txt", tmp_path, timestamp=now))
        debouncer.clear()
        
        ready = debouncer.flush_all()
        assert len(ready) == 0


class TestEventBatcher:
    """Tests for EventBatcher class."""

    def test_add_below_batch_size(self, tmp_path):
        batcher = EventBatcher(batch_size=10, batch_timeout_ms=1000)
        
        event = FileEvent(EventType.ADD, tmp_path / "file.txt", tmp_path)
        result = batcher.add(event)
        
        assert result is None
        assert batcher.pending_count() == 1

    def test_add_reaches_batch_size(self, tmp_path):
        batcher = EventBatcher(batch_size=3, batch_timeout_ms=1000)
        
        for i in range(2):
            batcher.add(FileEvent(EventType.ADD, tmp_path / f"file{i}.txt", tmp_path))
        
        result = batcher.add(FileEvent(EventType.ADD, tmp_path / "file2.txt", tmp_path))
        
        assert result is not None
        assert isinstance(result, EventBatch)
        assert len(result) == 3
        assert batcher.pending_count() == 0

    def test_add_multiple(self, tmp_path):
        batcher = EventBatcher(batch_size=5, batch_timeout_ms=1000)
        
        events = [FileEvent(EventType.ADD, tmp_path / f"f{i}.txt", tmp_path) for i in range(12)]
        batches = batcher.add_multiple(events)
        
        assert len(batches) == 2  # 5 + 5, with 2 remaining
        assert batcher.pending_count() == 2

    def test_check_timeout(self, tmp_path):
        batcher = EventBatcher(batch_size=100, batch_timeout_ms=50)
        now = time.time()
        
        event = FileEvent(EventType.ADD, tmp_path / "file.txt", tmp_path, timestamp=now)
        batcher.add(event)
        
        # Before timeout
        result = batcher.check_timeout(now + 0.03)
        assert result is None
        
        # After timeout
        result = batcher.check_timeout(now + 0.1)
        assert result is not None
        assert len(result) == 1

    def test_flush(self, tmp_path):
        batcher = EventBatcher(batch_size=100, batch_timeout_ms=1000)
        
        batcher.add(FileEvent(EventType.ADD, tmp_path / "a.txt", tmp_path))
        batcher.add(FileEvent(EventType.ADD, tmp_path / "b.txt", tmp_path))
        
        result = batcher.flush()
        
        assert result is not None
        assert len(result) == 2
        assert batcher.pending_count() == 0

    def test_flush_empty(self):
        batcher = EventBatcher(batch_size=10, batch_timeout_ms=1000)
        result = batcher.flush()
        assert result is None

    def test_on_batch_ready_callback(self, tmp_path):
        batches_received = []
        
        def callback(batch):
            batches_received.append(batch)
        
        batcher = EventBatcher(batch_size=2, batch_timeout_ms=1000, on_batch_ready=callback)
        
        batcher.add(FileEvent(EventType.ADD, tmp_path / "a.txt", tmp_path))
        batcher.add(FileEvent(EventType.ADD, tmp_path / "b.txt", tmp_path))
        
        assert len(batches_received) == 1
        assert len(batches_received[0]) == 2

    def test_clear(self, tmp_path):
        batcher = EventBatcher(batch_size=10, batch_timeout_ms=1000)
        
        batcher.add(FileEvent(EventType.ADD, tmp_path / "file.txt", tmp_path))
        batcher.clear()
        
        assert batcher.pending_count() == 0


class TestEventProcessor:
    """Tests for EventProcessor class."""

    def test_process_create_event(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        batches = []
        processor = EventProcessor(
            root_manager,
            WatcherConfig(debounce_ms=10, batch_size=1, move_correlation_ms=10),
            on_batch_ready=batches.append,
        )
        
        file_path = tmp_path / "test.txt"
        file_path.write_text("content")
        
        raw_event = RawFSEvent(
            event_type="created",
            src_path=file_path,
            timestamp=time.time(),
        )
        processor.process(raw_event)
        
        # Wait for debounce and flush
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        assert any(e.event_type == EventType.ADD for e in all_events)

    def test_process_modify_event(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        config = WatcherConfig(debounce_ms=10, batch_size=1, move_correlation_ms=10)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        file_path = tmp_path / "test.txt"
        file_path.write_text("content")
        
        raw_event = RawFSEvent(
            event_type="modified",
            src_path=file_path,
            timestamp=time.time(),
        )
        processor.process(raw_event)
        
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        assert any(e.event_type == EventType.UPDATE for e in all_events)

    def test_process_delete_event(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        config = WatcherConfig(debounce_ms=10, batch_size=1, move_correlation_ms=10)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        file_path = tmp_path / "test.txt"
        
        raw_event = RawFSEvent(
            event_type="deleted",
            src_path=file_path,
            timestamp=time.time(),
        )
        processor.process(raw_event)
        
        # Wait for move correlation window + debounce
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        assert any(e.event_type == EventType.DELETE for e in all_events)

    def test_process_move_event(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        config = WatcherConfig(debounce_ms=10, batch_size=1, move_correlation_ms=10)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        old_path = tmp_path / "old.txt"
        new_path = tmp_path / "new.txt"
        new_path.write_text("content")
        
        raw_event = RawFSEvent(
            event_type="moved",
            src_path=old_path,
            dest_path=new_path,
            timestamp=time.time(),
        )
        processor.process(raw_event)
        
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        move_events = [e for e in all_events if e.event_type == EventType.MOVE]
        assert len(move_events) == 1
        assert move_events[0].path == new_path.resolve()
        assert move_events[0].old_path == old_path.resolve()

    def test_process_move_out_of_roots_is_delete(self, tmp_path):
        root = tmp_path / "watched"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        
        root_manager = RootManager()
        root_manager.add_root(root)
        
        config = WatcherConfig(debounce_ms=10, batch_size=1, move_correlation_ms=10)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        raw_event = RawFSEvent(
            event_type="moved",
            src_path=root / "file.txt",
            dest_path=outside / "file.txt",
            timestamp=time.time(),
        )
        processor.process(raw_event)
        
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        assert any(e.event_type == EventType.DELETE for e in all_events)

    def test_process_move_into_roots_is_add(self, tmp_path):
        root = tmp_path / "watched"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        
        root_manager = RootManager()
        root_manager.add_root(root)
        
        dest_file = root / "file.txt"
        dest_file.write_text("content")
        
        config = WatcherConfig(debounce_ms=10, batch_size=1, move_correlation_ms=10)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        raw_event = RawFSEvent(
            event_type="moved",
            src_path=outside / "file.txt",
            dest_path=dest_file,
            timestamp=time.time(),
        )
        processor.process(raw_event)
        
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        assert any(e.event_type == EventType.ADD for e in all_events)

    def test_delete_create_correlation_becomes_move(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        config = WatcherConfig(debounce_ms=10, batch_size=10, move_correlation_ms=100)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        old_path = tmp_path / "file.txt"
        new_path = tmp_path / "subdir" / "file.txt"
        (tmp_path / "subdir").mkdir()
        new_path.write_text("content")
        
        now = time.time()
        
        # Delete then create with same filename
        processor.process(RawFSEvent("deleted", old_path, timestamp=now))
        processor.process(RawFSEvent("created", new_path, timestamp=now + 0.01))
        
        time.sleep(0.15)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        move_events = [e for e in all_events if e.event_type == EventType.MOVE]
        assert len(move_events) == 1

    def test_content_hash_computed(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        config = WatcherConfig(debounce_ms=10, batch_size=1, compute_hashes=True)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        file_path = tmp_path / "test.txt"
        file_path.write_text("hello world")
        
        processor.process(RawFSEvent("created", file_path, timestamp=time.time()))
        
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        assert any(e.content_hash is not None for e in all_events)

    def test_content_hash_disabled(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        config = WatcherConfig(debounce_ms=10, batch_size=1, compute_hashes=False)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        file_path = tmp_path / "test.txt"
        file_path.write_text("hello world")
        
        processor.process(RawFSEvent("created", file_path, timestamp=time.time()))
        
        time.sleep(0.05)
        processor.flush_all()
        
        assert len(batches) >= 1
        all_events = [e for b in batches for e in b.events]
        assert all(e.content_hash is None for e in all_events)

    def test_event_outside_roots_ignored(self, tmp_path):
        root = tmp_path / "watched"
        root.mkdir()
        
        root_manager = RootManager()
        root_manager.add_root(root)
        
        config = WatcherConfig(debounce_ms=10, batch_size=1)
        batches = []
        processor = EventProcessor(root_manager, config, on_batch_ready=batches.append)
        
        outside_file = tmp_path / "outside.txt"
        
        processor.process(RawFSEvent("created", outside_file, timestamp=time.time()))
        
        time.sleep(0.05)
        processor.flush_all()
        
        # No events should be generated
        all_events = [e for b in batches for e in b.events]
        assert len(all_events) == 0

    def test_clear(self, tmp_path):
        root_manager = RootManager()
        root_manager.add_root(tmp_path)
        
        config = WatcherConfig(debounce_ms=1000, batch_size=100)  # Long timeouts
        processor = EventProcessor(root_manager, config)
        
        processor.process(RawFSEvent("created", tmp_path / "file.txt", timestamp=time.time()))
        processor.clear()
        
        batches = processor.flush_all()
        assert len(batches) == 0 or all(len(b) == 0 for b in batches)
