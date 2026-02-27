"""
Activity logging for the indexer package.

Provides database-backed activity logging and a Python logging handler
that writes log records to SQLite.
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional


class ActivityLogger:
    """Logs indexer activities to an SQLite database."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_table()
    
    def _ensure_table(self) -> None:
        """Create activity_log table if it doesn't exist."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                path TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)
        conn.commit()
        conn.close()
    
    def log(self, activity_type: str, message: str, path: Optional[str] = None) -> None:
        """
        Log an activity to the activity_log table.
        
        Args:
            activity_type: Category of activity (e.g. 'root_added', 'error')
            message: Human-readable description
            path: Optional file/directory path related to the activity
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "INSERT INTO activity_log (type, message, path, created_at) VALUES (?, ?, ?, ?)",
                (activity_type, message, path, time.time()),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # Don't let logging errors break the application


class DatabaseLogHandler(logging.Handler):
    """Logging handler that writes log records to SQLite database."""
    
    def __init__(self, db_path: Path):
        super().__init__()
        self._activity = ActivityLogger(db_path)
    
    def emit(self, record: logging.LogRecord) -> None:
        """Write log record to database."""
        # Map log level to activity type
        level_map = {
            logging.DEBUG: 'debug',
            logging.INFO: 'info',
            logging.WARNING: 'warning',
            logging.ERROR: 'error',
            logging.CRITICAL: 'critical',
        }
        activity_type = level_map.get(record.levelno, 'info')
        
        # Format the message
        message = self.format(record)
        
        # Extract path if available in the record
        path = getattr(record, 'path', None)
        
        self._activity.log(activity_type, message, path)
