"""
Root directory management for the indexer package.

Handles adding/removing watched roots, scanning directories,
resync, and integrity reporting.
"""

import hashlib
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .activity import ActivityLogger
from .exceptions import RootOverlapError
from .models import IndexerEventType

logger = logging.getLogger(__name__)


class RootManager:
    """Manages watched root directories and their lifecycle.
    
    Args:
        watcher_db_path: Path to the watcher SQLite database
        store: VectorStore instance for document operations
        config: IndexerConfig for supported extensions etc.
        activity: ActivityLogger for logging activities
        watcher: Optional WatcherProcess for live watching
        index_file_fn: Callback to index a single file (returns IndexerEvent)
        stop_event: Threading event to signal cancellation
    """
    
    def __init__(
        self,
        watcher_db_path: Path,
        store,
        config,
        activity: ActivityLogger,
        watcher=None,
        index_file_fn: Optional[Callable] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self._watcher_db_path = watcher_db_path
        self._store = store
        self._config = config
        self._activity = activity
        self._watcher = watcher
        self._index_file_fn = index_file_fn
        self._stop_event = stop_event or threading.Event()
    
    def add_root(self, root: Path) -> bool:
        """Add a root directory to watch.
        
        Returns:
            True if root was added, False if it already exists.
            
        Raises:
            RootOverlapError: If the new root overlaps with an existing root.
        """
        logger.debug(f"add_root called with: {root}")
        if isinstance(root, str):
            root = Path(root)
        root = root.resolve()
        logger.debug(f"Resolved root path: {root}")
        logger.debug(f"Root exists: {root.exists()}, is_dir: {root.is_dir() if root.exists() else 'N/A'}")
        
        # Check for duplicate and save to watcher database
        conn = sqlite3.connect(str(self._watcher_db_path))
        # Ensure roots table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS roots (
                path TEXT PRIMARY KEY,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                enabled INTEGER DEFAULT 1
            )
        """)
        # Migrate: add enabled column if missing (existing databases)
        self._migrate_roots_table(conn)
        
        # Check if root already exists
        cursor = conn.execute("SELECT 1 FROM roots WHERE path = ?", (str(root),))
        result = cursor.fetchone()
        logger.debug(f"Database check for root '{root}': result={result}")
        
        # Also log all existing roots for debugging
        all_roots_cursor = conn.execute("SELECT path FROM roots")
        all_roots = [r[0] for r in all_roots_cursor.fetchall()]
        logger.debug(f"All roots in database: {all_roots}")
        
        if result:
            conn.close()
            logger.info(f"Root already exists: {root}")
            return False
        
        # Check for overlapping roots (parent/child relationships)
        self._check_root_overlap(root, all_roots, conn)
        
        conn.execute("INSERT INTO roots (path) VALUES (?)", (str(root),))
        conn.commit()
        conn.close()
        logger.info(f"Saved root to database: {root}")
        
        # Log activity
        self._activity.log("root_added", f"Added document folder: {root.name}", str(root))
        
        if self._watcher:
            self._watcher.add_root(root)
            logger.info(f"Queued root for watching: {root}")
        
        # Scan and index files in background thread (don't block API response)
        scan_thread = threading.Thread(target=self.scan_root, args=(root,), daemon=True)
        scan_thread.start()
        logger.info(f"Started background scan for root: {root}")
        return True
    
    @staticmethod
    def _check_root_overlap(new_root: Path, existing_roots: List[str], conn: sqlite3.Connection) -> None:
        """Check if new_root overlaps with any existing root.
        
        Raises:
            RootOverlapError: If overlap is detected. Closes conn before raising.
        """
        for existing_str in existing_roots:
            existing = Path(existing_str)
            try:
                new_root.relative_to(existing)
                # new_root is a child of existing
                conn.close()
                raise RootOverlapError(
                    f"'{new_root.name}' is already inside the managed folder '{existing.name}' ({existing})",
                    existing_root=existing_str,
                    new_root=str(new_root),
                    relationship="child",
                )
            except ValueError:
                pass
            try:
                existing.relative_to(new_root)
                # new_root is a parent of existing
                conn.close()
                raise RootOverlapError(
                    f"'{new_root.name}' contains the already-managed folder '{existing.name}' ({existing})",
                    existing_root=existing_str,
                    new_root=str(new_root),
                    relationship="parent",
                )
            except ValueError:
                pass

    @staticmethod
    def _migrate_roots_table(conn: sqlite3.Connection) -> None:
        """Add enabled column to roots table if it doesn't exist yet."""
        cursor = conn.execute("PRAGMA table_info(roots)")
        columns = {row[1] for row in cursor.fetchall()}
        if "enabled" not in columns:
            conn.execute("ALTER TABLE roots ADD COLUMN enabled INTEGER DEFAULT 1")
            conn.commit()
            logger.info("Migrated roots table: added 'enabled' column")

    def set_root_enabled(self, root: Path, enabled: bool) -> bool:
        """Enable or disable a root directory.
        
        Returns:
            True if the root was found and updated, False otherwise.
        """
        if isinstance(root, str):
            root = Path(root)
        root = root.resolve()
        
        conn = sqlite3.connect(str(self._watcher_db_path))
        cursor = conn.execute(
            "UPDATE roots SET enabled = ? WHERE path = ?",
            (1 if enabled else 0, str(root)),
        )
        conn.commit()
        updated = cursor.rowcount > 0
        conn.close()
        
        if updated:
            state = "enabled" if enabled else "disabled"
            logger.info(f"Root {state}: {root}")
            self._activity.log(
                f"root_{state}",
                f"{'Enabled' if enabled else 'Disabled'} document folder: {root.name}",
                str(root),
            )
        return updated

    def get_disabled_root_paths(self) -> List[str]:
        """Get paths of all disabled roots."""
        conn = sqlite3.connect(str(self._watcher_db_path))
        cursor = conn.execute("SELECT path FROM roots WHERE enabled = 0")
        paths = [row[0] for row in cursor.fetchall()]
        conn.close()
        return paths

    def remove_root(self, root: Path) -> None:
        """Remove a root directory from watching."""
        if isinstance(root, str):
            root = Path(root)
        root = root.resolve()
        
        # Immediately remove documents from vector store
        removed_count = self._store.remove_documents_under_path(root)
        logger.info(f"Removed {removed_count} documents from store for root: {root}")
        
        # Log activity
        self._activity.log(
            "root_removed",
            f"Removed document folder: {root.name} ({removed_count} documents)",
            str(root),
        )
        
        # Remove root from watcher database immediately for UI visibility
        conn = sqlite3.connect(str(self._watcher_db_path))
        conn.execute("DELETE FROM roots WHERE path = ?", (str(root),))
        conn.commit()
        conn.close()
        logger.info(f"Removed root from database: {root}")
        
        if self._watcher:
            self._watcher.remove_root(root)
            logger.info(f"Queued root removal from watcher: {root}")
    
    def get_roots(self) -> List[Path]:
        """Get current watched roots."""
        if self._watcher:
            return list(self._watcher.get_roots())
        return []
    
    def resync(self) -> None:
        """Queue a full resync via the watcher."""
        if self._watcher:
            self._watcher.resync()
            logger.info("Queued resync command")
        else:
            logger.warning("Cannot resync: watcher not running")
    
    def integrity_check(self) -> None:
        """Queue an integrity check via the watcher."""
        if self._watcher:
            self._watcher.integrity_check()
            logger.info("Queued integrity check command")
        else:
            logger.warning("Cannot run integrity check: watcher not running")
    
    def build_integrity_report(self, max_items: int = 10) -> Dict[str, Any]:
        """Build an integrity report comparing indexed files vs watched roots."""
        if not self._watcher:
            return {"error": "No watcher available"}
        
        roots = self._watcher.get_roots()
        indexed_files = set(self._store.get_all_file_paths())
        stats = self._store.get_stats()
        
        actual_files: Set[Path] = set()
        files_by_root = []
        for root in roots:
            root_files = []
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                if not self._config.is_supported(file_path):
                    continue
                resolved = file_path.resolve()
                actual_files.add(resolved)
                root_files.append(resolved)
            files_by_root.append({"root": str(root), "count": len(root_files)})
        
        missing_from_index = actual_files - indexed_files
        orphaned_in_index = indexed_files - actual_files
        in_both = actual_files & indexed_files
        
        modified_files = []
        for file_path in in_both:
            try:
                doc = self._store.get_document(file_path)
                if doc:
                    current_hash = _compute_file_hash(file_path)
                    if current_hash != doc.content_hash:
                        modified_files.append(file_path)
            except Exception:
                pass
        
        total_issues = len(missing_from_index) + len(orphaned_in_index) + len(modified_files)
        
        return {
            "roots": [str(root) for root in roots],
            "stats": {
                "document_count": stats.get("document_count", 0),
                "chunk_count": stats.get("chunk_count", 0),
                "embedding_count": stats.get("embedding_count", 0),
            },
            "files_by_root": files_by_root,
            "totals": {
                "indexed_files": len(indexed_files),
                "actual_files": len(actual_files),
                "in_sync": len(in_both) - len(modified_files),
            },
            "missing_from_index": {
                "count": len(missing_from_index),
                "sample": [str(p) for p in list(missing_from_index)[:max_items]],
            },
            "orphaned_in_index": {
                "count": len(orphaned_in_index),
                "sample": [str(p) for p in list(orphaned_in_index)[:max_items]],
            },
            "modified_files": {
                "count": len(modified_files),
                "sample": [str(p) for p in modified_files[:max_items]],
            },
            "issues": total_issues,
            "in_sync": total_issues == 0,
        }
    
    def scan_root(self, root: Path) -> int:
        """Scan and index files in a single root directory."""
        logger.debug(f"scan_root called with: {root}")
        if not root.exists():
            logger.warning(f"Root does not exist: {root}")
            return 0
        
        if self._index_file_fn is None:
            logger.error("No index_file_fn provided, cannot scan root")
            return 0
        
        logger.info(f"Scanning root: {root}")
        indexed_count = 0
        file_count = 0
        skipped_count = 0
        
        for file_path in root.rglob("*"):
            if self._stop_event.is_set():
                logger.debug("Stop event set, breaking scan loop")
                break
            
            if not file_path.is_file():
                continue
            
            file_count += 1
            
            if not self._config.is_supported(file_path):
                logger.debug(f"Skipping unsupported file: {file_path}")
                skipped_count += 1
                continue
            
            logger.debug(f"Processing file: {file_path}")
            try:
                result = self._index_file_fn(file_path)
                logger.debug(
                    f"Index result for {file_path}: type={result.event_type}, "
                    f"chunks={result.chunk_count}, error={result.error_message}"
                )
                if result.event_type == IndexerEventType.INDEXED and result.chunk_count > 0:
                    indexed_count += 1
                    logger.info(f"Indexed: {file_path} ({result.chunk_count} chunks)")
                elif result.event_type == IndexerEventType.FAILED:
                    logger.error(f"Failed to index {file_path}: {result.error_message}")
            except Exception as e:
                logger.error(f"Exception indexing {file_path}: {e}", exc_info=True)
        
        logger.info(f"Root scan complete: {root} (found={file_count}, indexed={indexed_count}, skipped={skipped_count})")
        return indexed_count
    
    def handle_resync(self) -> None:
        """Handle resync event — sync indexed files with actual files in all roots."""
        logger.info("Starting full resync...")
        
        if not self._watcher:
            logger.warning("No watcher available for resync")
            return
        
        if self._index_file_fn is None:
            logger.error("No index_file_fn provided, cannot resync")
            return
        
        roots = self._watcher.get_roots()
        if not roots:
            logger.info("No roots to resync")
            return
        
        # Get all currently indexed files
        indexed_files = set(self._store.get_all_file_paths())
        logger.info(f"Currently indexed: {len(indexed_files)} files")
        
        # Scan all files in roots
        actual_files: Set[Path] = set()
        for root in roots:
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                if not self._config.is_supported(file_path):
                    continue
                actual_files.add(file_path.resolve())
        
        logger.info(f"Found {len(actual_files)} files in roots")
        
        # Files to add (in roots but not indexed)
        to_add = actual_files - indexed_files
        # Files to remove (indexed but not in roots)
        to_remove = indexed_files - actual_files
        # Files to check for updates (in both)
        to_check = actual_files & indexed_files
        
        added_count = 0
        removed_count = 0
        updated_count = 0
        
        # Remove deleted files
        for file_path in to_remove:
            if self._stop_event.is_set():
                break
            try:
                self._store.remove_document(file_path)
                removed_count += 1
            except Exception as e:
                logger.error(f"Failed to remove {file_path}: {e}")
        
        # Add new files
        for file_path in to_add:
            if self._stop_event.is_set():
                break
            try:
                result = self._index_file_fn(file_path)
                if result.event_type == IndexerEventType.INDEXED and result.chunk_count > 0:
                    added_count += 1
            except Exception as e:
                logger.error(f"Failed to index {file_path}: {e}")
        
        # Check for updates (compare content hash)
        for file_path in to_check:
            if self._stop_event.is_set():
                break
            try:
                doc = self._store.get_document(file_path)
                if doc:
                    current_hash = _compute_file_hash(file_path)
                    if current_hash != doc.content_hash:
                        result = self._index_file_fn(file_path)
                        if result.event_type == IndexerEventType.INDEXED:
                            updated_count += 1
            except Exception as e:
                logger.error(f"Failed to check {file_path}: {e}")
        
        logger.info(f"Resync complete: {added_count} added, {removed_count} removed, {updated_count} updated")
    
    def handle_integrity_check(self) -> None:
        """Handle integrity check event — report and log results."""
        report = self.build_integrity_report()
        if "error" in report:
            logger.warning(report["error"])
            return
        
        logger.info("=" * 60)
        logger.info("INTEGRITY CHECK REPORT")
        logger.info("=" * 60)
        logger.info(f"\nWatched Roots ({len(report['roots'])}):")
        for root in report["roots"]:
            logger.info(f"  - {root}")
        
        stats = report["stats"]
        logger.info(f"\nIndexed Documents:")
        logger.info(f"  Total documents: {stats.get('document_count', 0)}")
        logger.info(f"  Total chunks: {stats.get('chunk_count', 0)}")
        logger.info(f"  Total embeddings: {stats.get('embedding_count', 0)}")
        
        logger.info(f"\nFiles in Watched Roots:")
        for item in report["files_by_root"]:
            logger.info(f"  {item['root']}: {item['count']} files")
        logger.info(f"  Total: {report['totals']['actual_files']} files")
        
        logger.info(f"\nIntegrity Status:")
        logger.info(f"  Files in sync: {report['totals']['in_sync']}")
        logger.info(f"  Missing from index (need add): {report['missing_from_index']['count']}")
        logger.info(f"  Orphaned in index (need remove): {report['orphaned_in_index']['count']}")
        logger.info(f"  Modified (need update): {report['modified_files']['count']}")
        
        if report["missing_from_index"]["sample"]:
            logger.info(f"\nMissing from index:")
            for f in report["missing_from_index"]["sample"]:
                logger.info(f"  + {f}")
            if report["missing_from_index"]["count"] > len(report["missing_from_index"]["sample"]):
                logger.info(
                    f"  ... and {report['missing_from_index']['count'] - len(report['missing_from_index']['sample'])} more"
                )
        
        if report["orphaned_in_index"]["sample"]:
            logger.info(f"\nOrphaned in index:")
            for f in report["orphaned_in_index"]["sample"]:
                logger.info(f"  - {f}")
            if report["orphaned_in_index"]["count"] > len(report["orphaned_in_index"]["sample"]):
                logger.info(
                    f"  ... and {report['orphaned_in_index']['count'] - len(report['orphaned_in_index']['sample'])} more"
                )
        
        if report["modified_files"]["sample"]:
            logger.info(f"\nModified files:")
            for f in report["modified_files"]["sample"]:
                logger.info(f"  ~ {f}")
            if report["modified_files"]["count"] > len(report["modified_files"]["sample"]):
                logger.info(
                    f"  ... and {report['modified_files']['count'] - len(report['modified_files']['sample'])} more"
                )
        
        if report["in_sync"]:
            logger.info(f"\n✓ Index is in sync with watched files")
        else:
            logger.info(f"\n⚠ Index has {report['issues']} issue(s). Run 'resync' to fix.")
        
        logger.info("=" * 60)


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of file content."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
