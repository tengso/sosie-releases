"""SQLite-backed persistent queue implementation."""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Tuple, Optional, Any

from .exceptions import QueueError, QueueCorruptionError


class PersistentQueue:
    """
    SQLite-backed FIFO queue with durability and batch support.
    
    Features:
    - Atomic enqueue/dequeue operations
    - Crash recovery via requeue_unacked
    - Batch dequeue for efficiency
    - Thread-safe operations
    """

    def __init__(self, db_path: Path, table_name: str = "queue"):
        """
        Initialize the persistent queue.
        
        Args:
            db_path: Path to the SQLite database file
            table_name: Name of the table for this queue
        """
        self.db_path = db_path
        self.table_name = table_name
        self._lock = threading.Lock()
        self._local = threading.local()
        self._closed = False
        
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode
            )
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self) -> None:
        """Initialize the database schema."""
        conn = self._get_connection()
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table_name}_status 
            ON {self.table_name}(status)
        """)

    def enqueue(self, item: Any) -> int:
        """
        Add an item to the queue.
        
        Args:
            item: Item to enqueue (must be JSON-serializable)
            
        Returns:
            The ID of the enqueued item
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        payload = json.dumps(item)
        now = time.time()
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                f"INSERT INTO {self.table_name} (payload, status, created_at, updated_at) VALUES (?, 'pending', ?, ?)",
                (payload, now, now)
            )
            return cursor.lastrowid

    def enqueue_batch(self, items: List[Any]) -> List[int]:
        """
        Add multiple items to the queue atomically.
        
        Args:
            items: List of items to enqueue
            
        Returns:
            List of IDs for the enqueued items
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        if not items:
            return []
        
        now = time.time()
        payloads = [(json.dumps(item), now, now) for item in items]
        
        with self._lock:
            conn = self._get_connection()
            conn.execute("BEGIN")
            try:
                ids = []
                for payload, created, updated in payloads:
                    cursor = conn.execute(
                        f"INSERT INTO {self.table_name} (payload, status, created_at, updated_at) VALUES (?, 'pending', ?, ?)",
                        (payload, created, updated)
                    )
                    ids.append(cursor.lastrowid)
                conn.execute("COMMIT")
                return ids
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def dequeue(self, batch_size: int = 1) -> List[Tuple[int, Any]]:
        """
        Remove and return items from the queue.
        
        Items are marked as 'processing' until acked.
        
        Args:
            batch_size: Maximum number of items to dequeue
            
        Returns:
            List of (id, item) tuples
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        now = time.time()
        
        with self._lock:
            conn = self._get_connection()
            conn.execute("BEGIN")
            try:
                cursor = conn.execute(
                    f"SELECT id, payload FROM {self.table_name} WHERE status = 'pending' ORDER BY id LIMIT ?",
                    (batch_size,)
                )
                rows = cursor.fetchall()
                
                if rows:
                    ids = [row[0] for row in rows]
                    placeholders = ",".join("?" * len(ids))
                    conn.execute(
                        f"UPDATE {self.table_name} SET status = 'processing', updated_at = ? WHERE id IN ({placeholders})",
                        [now] + ids
                    )
                
                conn.execute("COMMIT")
                return [(row[0], json.loads(row[1])) for row in rows]
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def peek(self, batch_size: int = 1) -> List[Tuple[int, Any]]:
        """
        View items without removing them from the queue.
        
        Args:
            batch_size: Maximum number of items to peek
            
        Returns:
            List of (id, item) tuples
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                f"SELECT id, payload FROM {self.table_name} WHERE status = 'pending' ORDER BY id LIMIT ?",
                (batch_size,)
            )
            return [(row[0], json.loads(row[1])) for row in cursor.fetchall()]

    def ack(self, ids: List[int]) -> None:
        """
        Acknowledge items as successfully processed.
        
        Args:
            ids: List of item IDs to acknowledge
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        if not ids:
            return
        
        with self._lock:
            conn = self._get_connection()
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM {self.table_name} WHERE id IN ({placeholders})",
                ids
            )

    def nack(self, ids: List[int]) -> None:
        """
        Negative acknowledge - return items to pending state.
        
        Args:
            ids: List of item IDs to return to queue
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        if not ids:
            return
        
        now = time.time()
        
        with self._lock:
            conn = self._get_connection()
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE {self.table_name} SET status = 'pending', updated_at = ? WHERE id IN ({placeholders})",
                [now] + ids
            )

    def requeue_unacked(self) -> int:
        """
        Requeue all items that were being processed (crash recovery).
        
        Returns:
            Number of items requeued
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        now = time.time()
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                f"UPDATE {self.table_name} SET status = 'pending', updated_at = ? WHERE status = 'processing'",
                (now,)
            )
            return cursor.rowcount

    def size(self) -> int:
        """
        Get the number of pending items in the queue.
        
        Returns:
            Number of pending items
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM {self.table_name} WHERE status = 'pending'"
            )
            return cursor.fetchone()[0]

    def total_size(self) -> int:
        """
        Get the total number of items in the queue (including processing).
        
        Returns:
            Total number of items
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM {self.table_name}"
            )
            return cursor.fetchone()[0]

    def clear(self) -> int:
        """
        Remove all items from the queue.
        
        Returns:
            Number of items removed
        """
        if self._closed:
            raise QueueError("Queue is closed")
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(f"DELETE FROM {self.table_name}")
            return cursor.rowcount

    def close(self) -> None:
        """Close the queue and release resources."""
        if self._closed:
            return
        
        self._closed = True
        
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
