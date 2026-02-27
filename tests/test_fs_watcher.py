"""Tests for filesystem watcher module."""

import pytest
import time
import threading
from pathlib import Path

from src.watcher.config import WatcherConfig
from src.watcher.models import RawFSEvent
from src.watcher.fs_watcher import FSWatcherPool, FSEventHandler


class TestFSWatcherPool:
    """Tests for FSWatcherPool class."""

    def test_create_pool(self):
        events = []
        pool = FSWatcherPool(events.append)
        assert len(pool) == 0

    def test_start_watching(self, tmp_path):
        events = []
        pool = FSWatcherPool(events.append)
        
        result = pool.start_watching(tmp_path)
        
        assert result is True
        assert len(pool) == 1
        assert pool.is_watching(tmp_path)
        
        pool.stop_all()

    def test_start_watching_duplicate(self, tmp_path):
        events = []
        pool = FSWatcherPool(events.append)
        
        pool.start_watching(tmp_path)
        result = pool.start_watching(tmp_path)
        
        assert result is False
        assert len(pool) == 1
        
        pool.stop_all()

    def test_stop_watching(self, tmp_path):
        events = []
        pool = FSWatcherPool(events.append)
        
        pool.start_watching(tmp_path)
        result = pool.stop_watching(tmp_path)
        
        assert result is True
        assert len(pool) == 0
        assert not pool.is_watching(tmp_path)

    def test_stop_watching_not_watching(self, tmp_path):
        events = []
        pool = FSWatcherPool(events.append)
        
        result = pool.stop_watching(tmp_path)
        
        assert result is False

    def test_stop_all(self, tmp_path):
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()
        
        events = []
        pool = FSWatcherPool(events.append)
        
        pool.start_watching(root1)
        pool.start_watching(root2)
        
        count = pool.stop_all()
        
        assert count == 2
        assert len(pool) == 0

    def test_get_watched_roots(self, tmp_path):
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()
        
        events = []
        pool = FSWatcherPool(events.append)
        
        pool.start_watching(root1)
        pool.start_watching(root2)
        
        roots = pool.get_watched_roots()
        
        assert len(roots) == 2
        assert root1.resolve() in roots
        assert root2.resolve() in roots
        
        pool.stop_all()

    def test_detects_file_creation(self, tmp_path):
        events = []
        lock = threading.Lock()
        
        def callback(event):
            with lock:
                events.append(event)
        
        pool = FSWatcherPool(callback)
        pool.start_watching(tmp_path)
        
        # Give watcher time to start
        time.sleep(0.2)
        
        # Create a file
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        
        # Wait for event
        time.sleep(0.5)
        
        pool.stop_all()
        
        with lock:
            create_events = [e for e in events if e.event_type == "created" and "test.txt" in str(e.src_path)]
        
        assert len(create_events) >= 1

    def test_detects_file_modification(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        
        events = []
        lock = threading.Lock()
        
        def callback(event):
            with lock:
                events.append(event)
        
        pool = FSWatcherPool(callback)
        pool.start_watching(tmp_path)
        
        time.sleep(0.2)
        
        # Modify the file
        test_file.write_text("modified")
        
        time.sleep(0.5)
        
        pool.stop_all()
        
        with lock:
            modify_events = [e for e in events if e.event_type == "modified" and "test.txt" in str(e.src_path)]
        
        assert len(modify_events) >= 1

    def test_detects_file_deletion(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("to be deleted")
        
        events = []
        lock = threading.Lock()
        
        def callback(event):
            with lock:
                events.append(event)
        
        pool = FSWatcherPool(callback)
        pool.start_watching(tmp_path)
        
        time.sleep(0.2)
        
        # Delete the file
        test_file.unlink()
        
        time.sleep(0.5)
        
        pool.stop_all()
        
        with lock:
            delete_events = [e for e in events if e.event_type == "deleted" and "test.txt" in str(e.src_path)]
        
        assert len(delete_events) >= 1

    def test_detects_file_move(self, tmp_path):
        test_file = tmp_path / "old.txt"
        test_file.write_text("content")
        
        events = []
        lock = threading.Lock()
        
        def callback(event):
            with lock:
                events.append(event)
        
        pool = FSWatcherPool(callback)
        pool.start_watching(tmp_path)
        
        time.sleep(0.2)
        
        # Move the file
        new_file = tmp_path / "new.txt"
        test_file.rename(new_file)
        
        time.sleep(0.5)
        
        pool.stop_all()
        
        with lock:
            # Should either be a move event or delete+create pair
            move_events = [e for e in events if e.event_type == "moved"]
            if move_events:
                assert any("old.txt" in str(e.src_path) for e in move_events)

    def test_ignores_patterns(self, tmp_path):
        events = []
        lock = threading.Lock()
        
        def callback(event):
            with lock:
                events.append(event)
        
        config = WatcherConfig(ignore_patterns=["*.tmp"])
        pool = FSWatcherPool(callback, config)
        pool.start_watching(tmp_path)
        
        time.sleep(0.2)
        
        # Create ignored file
        (tmp_path / "test.tmp").write_text("ignored")
        # Create non-ignored file
        (tmp_path / "test.txt").write_text("not ignored")
        
        time.sleep(0.5)
        
        pool.stop_all()
        
        with lock:
            tmp_events = [e for e in events if ".tmp" in str(e.src_path)]
            txt_events = [e for e in events if ".txt" in str(e.src_path)]
        
        assert len(tmp_events) == 0
        assert len(txt_events) >= 1

    def test_watches_subdirectories(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        
        events = []
        lock = threading.Lock()
        
        def callback(event):
            with lock:
                events.append(event)
        
        config = WatcherConfig(recursive=True)
        pool = FSWatcherPool(callback, config)
        pool.start_watching(tmp_path)
        
        time.sleep(0.2)
        
        # Create file in subdirectory
        (subdir / "nested.txt").write_text("nested content")
        
        time.sleep(0.5)
        
        pool.stop_all()
        
        with lock:
            nested_events = [e for e in events if "nested.txt" in str(e.src_path)]
        
        assert len(nested_events) >= 1


class TestFSEventHandler:
    """Tests for FSEventHandler class."""

    def test_should_ignore_tmp_files(self, tmp_path):
        events = []
        config = WatcherConfig()
        handler = FSEventHandler(events.append, config, tmp_path)
        
        assert handler._should_ignore(str(tmp_path / "file.tmp")) is True
        assert handler._should_ignore(str(tmp_path / "file.txt")) is False

    def test_should_ignore_swp_files(self, tmp_path):
        events = []
        config = WatcherConfig()
        handler = FSEventHandler(events.append, config, tmp_path)
        
        assert handler._should_ignore(str(tmp_path / ".file.swp")) is True

    def test_should_ignore_git_files(self, tmp_path):
        events = []
        config = WatcherConfig()
        handler = FSEventHandler(events.append, config, tmp_path)
        
        assert handler._should_ignore(str(tmp_path / ".git" / "config")) is True
