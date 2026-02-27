"""Configuration for the file watcher package."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class WatcherConfig:
    """
    Configuration options for the file watcher.
    
    Attributes:
        db_path: Path to the SQLite database for persistent queues
        debounce_ms: Milliseconds to wait before emitting coalesced events
        move_correlation_ms: Time window to correlate DELETE+ADD as MOVE
        flush_interval_ms: Interval for flushing pending events
        batch_size: Maximum number of events per batch
        batch_timeout_ms: Maximum time to wait before emitting a partial batch
        compute_hashes: Whether to compute content hashes for files
        hash_algorithm: Algorithm for content hashing
        ignore_patterns: Glob patterns for files to ignore
        recursive: Whether to watch directories recursively
        follow_symlinks: Whether to follow symbolic links
    """
    db_path: Path = field(default_factory=lambda: Path("watcher.db"))
    debounce_ms: int = 50
    move_correlation_ms: int = 100
    flush_interval_ms: int = 100
    batch_size: int = 100
    batch_timeout_ms: int = 500
    compute_hashes: bool = True
    hash_algorithm: str = "sha256"
    ignore_patterns: List[str] = field(default_factory=lambda: [
        "*.tmp",
        "*.swp",
        "*.swo",
        "*~",
        ".git/*",
        ".git",
        "__pycache__/*",
        "__pycache__",
        "*.pyc",
        ".DS_Store",
        "Thumbs.db",
    ])
    recursive: bool = True
    follow_symlinks: bool = False

    def should_ignore(self, path: Path) -> bool:
        """
        Check if a path should be ignored based on ignore patterns.
        
        Args:
            path: Path to check
            
        Returns:
            True if the path should be ignored
        """
        import fnmatch
        
        path_str = str(path)
        name = path.name
        
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
            if fnmatch.fnmatch(path_str, f"*/{pattern}"):
                return True
            if fnmatch.fnmatch(path_str, pattern):
                return True
        
        return False
