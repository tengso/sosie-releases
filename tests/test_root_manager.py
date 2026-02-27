"""Tests for root manager module."""

import pytest
import threading
from pathlib import Path

from src.watcher.root_manager import RootManager
from src.watcher.exceptions import RootNotFoundError, RootAlreadyExistsError


class TestRootManager:
    """Tests for RootManager class."""

    def test_create_empty_manager(self):
        manager = RootManager()
        assert len(manager) == 0
        assert manager.get_roots() == frozenset()

    def test_add_root(self, tmp_path):
        manager = RootManager()
        result = manager.add_root(tmp_path)
        
        assert result is True
        assert len(manager) == 1
        assert tmp_path.resolve() in manager.get_roots()

    def test_add_nonexistent_root_raises(self):
        manager = RootManager()
        
        with pytest.raises(RootNotFoundError):
            manager.add_root(Path("/nonexistent/path/12345"))

    def test_add_nonexistent_root_allowed(self, tmp_path):
        manager = RootManager()
        nonexistent = tmp_path / "nonexistent"
        
        result = manager.add_root(nonexistent, must_exist=False)
        assert result is True

    def test_add_duplicate_root_raises(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        with pytest.raises(RootAlreadyExistsError):
            manager.add_root(tmp_path)

    def test_add_multiple_roots(self, tmp_path):
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()
        
        manager = RootManager()
        manager.add_root(root1)
        manager.add_root(root2)
        
        assert len(manager) == 2

    def test_remove_root(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        result = manager.remove_root(tmp_path)
        
        assert result is True
        assert len(manager) == 0

    def test_remove_nonexistent_root(self, tmp_path):
        manager = RootManager()
        
        result = manager.remove_root(tmp_path)
        assert result is False

    def test_get_roots_returns_frozen_set(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        roots = manager.get_roots()
        
        assert isinstance(roots, frozenset)
        with pytest.raises(AttributeError):
            roots.add(Path("/new/path"))

    def test_find_root_for_path(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        file_path = tmp_path / "subdir" / "file.txt"
        found_root = manager.find_root_for_path(file_path)
        
        assert found_root == tmp_path.resolve()

    def test_find_root_for_path_not_under_root(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        
        manager = RootManager()
        manager.add_root(root)
        
        other_path = tmp_path / "other" / "file.txt"
        found_root = manager.find_root_for_path(other_path)
        
        assert found_root is None

    def test_find_root_for_path_multiple_roots(self, tmp_path):
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()
        
        manager = RootManager()
        manager.add_root(root1)
        manager.add_root(root2)
        
        file1 = root1 / "file.txt"
        file2 = root2 / "file.txt"
        
        assert manager.find_root_for_path(file1) == root1.resolve()
        assert manager.find_root_for_path(file2) == root2.resolve()

    def test_is_under_any_root_true(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        file_path = tmp_path / "deep" / "nested" / "file.txt"
        
        assert manager.is_under_any_root(file_path) is True

    def test_is_under_any_root_false(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        
        manager = RootManager()
        manager.add_root(root)
        
        other_path = tmp_path / "other" / "file.txt"
        
        assert manager.is_under_any_root(other_path) is False

    def test_has_root(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        assert manager.has_root(tmp_path) is True
        assert manager.has_root(tmp_path / "subdir") is False

    def test_contains(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        assert tmp_path in manager
        assert (tmp_path / "subdir") not in manager

    def test_clear(self, tmp_path):
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()
        
        manager = RootManager()
        manager.add_root(root1)
        manager.add_root(root2)
        
        count = manager.clear()
        
        assert count == 2
        assert len(manager) == 0

    def test_path_resolution(self, tmp_path):
        manager = RootManager()
        
        # Create directory first
        actual = tmp_path / "actual"
        actual.mkdir()
        
        # Add with relative-like path (resolved)
        manager.add_root(tmp_path / "." / "subdir" / ".." / "actual")
        
        # Should find the resolved path
        assert actual.resolve() in manager.get_roots()

    def test_thread_safety(self, tmp_path):
        manager = RootManager()
        errors = []
        
        def add_roots():
            try:
                for i in range(10):
                    root = tmp_path / f"root_{threading.current_thread().name}_{i}"
                    root.mkdir(exist_ok=True)
                    try:
                        manager.add_root(root)
                    except RootAlreadyExistsError:
                        pass
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=add_roots, name=f"t{i}") for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(manager) == 50

    def test_thread_safety_find_root(self, tmp_path):
        manager = RootManager()
        manager.add_root(tmp_path)
        
        results = []
        errors = []
        
        def find_root():
            try:
                for _ in range(100):
                    result = manager.find_root_for_path(tmp_path / "file.txt")
                    results.append(result)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=find_root) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert all(r == tmp_path.resolve() for r in results)
