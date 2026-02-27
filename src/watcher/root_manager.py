"""Thread-safe management of watched root folders."""

import threading
from pathlib import Path
from typing import FrozenSet, Optional, Set

from .exceptions import RootNotFoundError, RootAlreadyExistsError


class RootManager:
    """
    Thread-safe management of root folders being watched.
    
    Provides methods to add/remove roots and query which root
    a given path belongs to.
    """

    def __init__(self):
        """Initialize the root manager."""
        self._roots: Set[Path] = set()
        self._lock = threading.RLock()

    def add_root(self, path: Path, must_exist: bool = True) -> bool:
        """
        Add a root folder to watch.
        
        Args:
            path: Path to the root folder
            must_exist: If True, raise error if path doesn't exist
            
        Returns:
            True if the root was added, False if already exists
            
        Raises:
            RootNotFoundError: If must_exist and path doesn't exist
            RootAlreadyExistsError: If the root is already being watched
        """
        path = path.resolve()
        
        if must_exist and not path.exists():
            raise RootNotFoundError(f"Root folder does not exist: {path}")
        
        with self._lock:
            if path in self._roots:
                raise RootAlreadyExistsError(f"Root already being watched: {path}")
            
            # Check for overlapping roots (parent/child)
            for existing in self._roots:
                try:
                    path.relative_to(existing)
                    raise RootAlreadyExistsError(
                        f"'{path}' is already inside watched root '{existing}'"
                    )
                except ValueError:
                    pass
                try:
                    existing.relative_to(path)
                    raise RootAlreadyExistsError(
                        f"'{path}' contains already-watched root '{existing}'"
                    )
                except ValueError:
                    pass
            
            self._roots.add(path)
            return True

    def remove_root(self, path: Path) -> bool:
        """
        Remove a root folder from watching.
        
        Args:
            path: Path to the root folder
            
        Returns:
            True if the root was removed, False if not found
        """
        path = path.resolve()
        
        with self._lock:
            if path in self._roots:
                self._roots.discard(path)
                return True
            return False

    def get_roots(self) -> FrozenSet[Path]:
        """
        Get the current set of root folders.
        
        Returns:
            Frozen set of root paths
        """
        with self._lock:
            return frozenset(self._roots)

    def find_root_for_path(self, path: Path) -> Optional[Path]:
        """
        Find which root folder contains the given path.
        
        Args:
            path: Path to check
            
        Returns:
            The root path that contains this path, or None
        """
        path = path.resolve()
        
        with self._lock:
            for root in self._roots:
                try:
                    path.relative_to(root)
                    return root
                except ValueError:
                    continue
            return None

    def is_under_any_root(self, path: Path) -> bool:
        """
        Check if a path is under any watched root.
        
        Args:
            path: Path to check
            
        Returns:
            True if the path is under a watched root
        """
        return self.find_root_for_path(path) is not None

    def has_root(self, path: Path) -> bool:
        """
        Check if a specific path is a watched root.
        
        Args:
            path: Path to check
            
        Returns:
            True if the path is a watched root
        """
        path = path.resolve()
        
        with self._lock:
            return path in self._roots

    def clear(self) -> int:
        """
        Remove all roots.
        
        Returns:
            Number of roots removed
        """
        with self._lock:
            count = len(self._roots)
            self._roots.clear()
            return count

    def __len__(self) -> int:
        """Return the number of watched roots."""
        with self._lock:
            return len(self._roots)

    def __contains__(self, path: Path) -> bool:
        """Check if a path is a watched root."""
        return self.has_root(path)
