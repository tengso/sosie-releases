"""Tests for config module."""

import pytest
from pathlib import Path

from src.watcher.config import WatcherConfig


class TestWatcherConfig:
    """Tests for WatcherConfig class."""

    def test_default_values(self):
        config = WatcherConfig()
        assert config.db_path == Path("watcher.db")
        assert config.debounce_ms == 50
        assert config.move_correlation_ms == 100
        assert config.flush_interval_ms == 100
        assert config.batch_size == 100
        assert config.batch_timeout_ms == 500
        assert config.compute_hashes is True
        assert config.hash_algorithm == "sha256"
        assert config.recursive is True
        assert config.follow_symlinks is False

    def test_custom_values(self, tmp_path):
        config = WatcherConfig(
            db_path=tmp_path / "custom.db",
            debounce_ms=100,
            batch_size=50,
            compute_hashes=False,
        )
        assert config.db_path == tmp_path / "custom.db"
        assert config.debounce_ms == 100
        assert config.batch_size == 50
        assert config.compute_hashes is False

    def test_ignore_patterns_default(self):
        config = WatcherConfig()
        assert "*.tmp" in config.ignore_patterns
        assert "*.swp" in config.ignore_patterns
        assert ".git/*" in config.ignore_patterns
        assert "__pycache__/*" in config.ignore_patterns

    def test_should_ignore_tmp_files(self):
        config = WatcherConfig()
        assert config.should_ignore(Path("/path/to/file.tmp")) is True
        assert config.should_ignore(Path("/path/to/file.swp")) is True
        assert config.should_ignore(Path("/path/to/file.swo")) is True

    def test_should_ignore_backup_files(self):
        config = WatcherConfig()
        assert config.should_ignore(Path("/path/to/file~")) is True

    def test_should_ignore_git_directory(self):
        config = WatcherConfig()
        assert config.should_ignore(Path("/repo/.git/config")) is True
        assert config.should_ignore(Path("/repo/.git/objects/abc")) is True

    def test_should_ignore_pycache(self):
        config = WatcherConfig()
        assert config.should_ignore(Path("/path/__pycache__/module.pyc")) is True
        assert config.should_ignore(Path("/path/to/file.pyc")) is True

    def test_should_ignore_os_files(self):
        config = WatcherConfig()
        assert config.should_ignore(Path("/path/.DS_Store")) is True
        assert config.should_ignore(Path("/path/Thumbs.db")) is True

    def test_should_not_ignore_normal_files(self):
        config = WatcherConfig()
        assert config.should_ignore(Path("/path/to/file.txt")) is False
        assert config.should_ignore(Path("/path/to/file.py")) is False
        assert config.should_ignore(Path("/path/to/file.js")) is False

    def test_custom_ignore_patterns(self):
        config = WatcherConfig(ignore_patterns=["*.log", "node_modules/*"])
        assert config.should_ignore(Path("/path/debug.log")) is True
        assert config.should_ignore(Path("/path/node_modules/package/index.js")) is True
        assert config.should_ignore(Path("/path/file.txt")) is False

    def test_empty_ignore_patterns(self):
        config = WatcherConfig(ignore_patterns=[])
        assert config.should_ignore(Path("/path/file.tmp")) is False
        assert config.should_ignore(Path("/path/.git/config")) is False
