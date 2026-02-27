"""
Authentication module for multi-user support.

Provides user management, password hashing, and session token handling.
Uses SQLite for storage and stdlib for crypto (no external deps).
"""

import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Session token lifetime
SESSION_LIFETIME_DAYS = 30
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class User:
    """Represents an authenticated user."""
    id: int
    username: str
    display_name: str
    avatar_url: Optional[str] = None
    email: Optional[str] = None
    picked_agents: List[str] = field(default_factory=lambda: ["doc_qa_agent", "deep_research_agent"])
    agent_overrides: Dict = field(default_factory=dict)
    knowledge_roots: Optional[Dict[str, Optional[List[str]]]] = None
    is_admin: bool = False
    created_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "email": self.email,
            "picked_agents": self.picked_agents,
            "agent_overrides": self.agent_overrides,
            "knowledge_roots": self.knowledge_roots,
            "is_admin": self.is_admin,
            "created_at": self.created_at,
        }


def _hash_password(password: str, salt: Optional[bytes] = None) -> tuple:
    """Hash password with PBKDF2-HMAC-SHA256. Returns (hash_hex, salt_hex)."""
    if salt is None:
        salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=100_000)
    return dk.hex(), salt.hex()


def _verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    """Verify password against stored hash."""
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=100_000)
    return dk.hex() == hash_hex


def _normalize_email(email: Optional[str]) -> Optional[str]:
    """Normalize and validate basic email shape."""
    if email is None:
        return None

    normalized = str(email).strip()
    if not normalized:
        return None

    if len(normalized) > 254 or not _EMAIL_PATTERN.match(normalized):
        raise ValueError("Invalid email address")

    return normalized


class AuthManager:
    """Manages users and session tokens in SQLite."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                display_name TEXT NOT NULL,
                avatar_url TEXT,
                email TEXT,
                picked_agents TEXT DEFAULT '["doc_qa_agent","deep_research_agent"]',
                agent_overrides TEXT DEFAULT '{}',
                is_admin INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions(expires_at);
        """)
        conn.commit()
        # Migration: add agent_overrides column if missing (for existing DBs)
        try:
            conn.execute("SELECT agent_overrides FROM users LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE users ADD COLUMN agent_overrides TEXT DEFAULT '{}'")
            conn.commit()
            logger.info("Migrated users table: added agent_overrides column")
        # Migration: add knowledge_roots column if missing
        try:
            conn.execute("SELECT knowledge_roots FROM users LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE users ADD COLUMN knowledge_roots TEXT")
            conn.commit()
            logger.info("Migrated users table: added knowledge_roots column")
        # Migration: add email column if missing
        try:
            conn.execute("SELECT email FROM users LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            conn.commit()
            logger.info("Migrated users table: added email column")
        conn.close()
        logger.debug("Auth database initialized at %s", self._db_path)

    def _row_to_user(self, row: sqlite3.Row) -> User:
        """Convert a DB row to a User object."""
        picked = json.loads(row["picked_agents"]) if row["picked_agents"] else []
        try:
            overrides = json.loads(row["agent_overrides"]) if row["agent_overrides"] else {}
        except (json.JSONDecodeError, KeyError):
            overrides = {}
        try:
            kr = json.loads(row["knowledge_roots"]) if row["knowledge_roots"] else None
            if isinstance(kr, list):
                kr = None  # old flat-list format → reset
            elif isinstance(kr, dict):
                # Strip numeric-key artifacts from old list→dict migration
                kr = {k: v for k, v in kr.items() if not k.isdigit()}
                # Simplify: if empty or all values are null, collapse to None
                if not kr or all(v is None for v in kr.values()):
                    kr = None
        except (json.JSONDecodeError, KeyError):
            kr = None
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            email=row["email"] if "email" in row.keys() else None,
            picked_agents=picked,
            agent_overrides=overrides,
            knowledge_roots=kr,
            is_admin=bool(row["is_admin"]),
            created_at=row["created_at"],
        )

    def user_count(self) -> int:
        """Return total number of registered users."""
        conn = self._connect()
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        conn.close()
        return count

    def create_user(
        self,
        username: str,
        password: str,
        display_name: Optional[str] = None,
        is_admin: bool = False,
        email: Optional[str] = None,
    ) -> User:
        """Create a new user. Raises ValueError if username taken."""
        _RESERVED_NAMES = {"shared_documents", "_service"}
        if not username or not username.strip():
            raise ValueError("Username is required")
        if username.strip().lower() in _RESERVED_NAMES:
            raise ValueError("This username is reserved")
        if not password or len(password) < 4:
            raise ValueError("Password must be at least 4 characters")

        username = username.strip().lower()
        display_name = (display_name or username).strip()
        email = _normalize_email(email)
        hash_hex, salt_hex = _hash_password(password)

        with self._lock:
            conn = self._connect()
            try:
                # First user is always admin
                if is_admin or conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
                    is_admin = True

                conn.execute(
                    """INSERT INTO users (username, password_hash, password_salt, display_name, is_admin, email)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (username, hash_hex, salt_hex, display_name, 1 if is_admin else 0, email),
                )
                conn.commit()
                user_id = conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()["id"]
                user = self.get_user_by_id(user_id, conn=conn)
                conn.close()
                logger.info("Created user: %s (admin=%s)", username, is_admin)
                return user
            except sqlite3.IntegrityError:
                conn.close()
                raise ValueError(f"Username '{username}' is already taken")

    def verify_login(self, username: str, password: str) -> Optional[User]:
        """Verify credentials. Returns User on success, None on failure."""
        username = username.strip().lower()
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            conn.close()
            return None
        if not _verify_password(password, row["password_hash"], row["password_salt"]):
            conn.close()
            return None
        user = self._row_to_user(row)
        conn.close()
        return user

    def get_user_by_id(self, user_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[User]:
        """Get user by ID."""
        should_close = conn is None
        if conn is None:
            conn = self._connect()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if should_close:
            conn.close()
        if row is None:
            return None
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_user(row)

    def update_user(self, user_id: int, **kwargs) -> Optional[User]:
        """Update user fields. Supported: display_name, avatar_url, email, picked_agents, agent_overrides, knowledge_roots."""
        allowed = {"display_name", "avatar_url", "email", "picked_agents", "agent_overrides", "knowledge_roots"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_user_by_id(user_id)

        with self._lock:
            conn = self._connect()
            for key, value in updates.items():
                if key == "email":
                    value = _normalize_email(value)
                if key in ("picked_agents", "agent_overrides", "knowledge_roots"):
                    value = json.dumps(value) if value is not None else None
                conn.execute(f"UPDATE users SET {key} = ? WHERE id = ?", (value, user_id))
            conn.commit()
            user = self.get_user_by_id(user_id, conn=conn)
            conn.close()
            return user

    def get_all_usernames(self) -> List[str]:
        """Get all usernames (for computing search exclusion lists)."""
        conn = self._connect()
        rows = conn.execute("SELECT username FROM users").fetchall()
        conn.close()
        return [r["username"] for r in rows]

    # ── Session tokens ──

    def create_session_token(self, user_id: int) -> str:
        """Create a new session token for a user."""
        token = secrets.token_urlsafe(48)
        expires_at = (datetime.utcnow() + timedelta(days=SESSION_LIFETIME_DAYS)).isoformat()

        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO auth_sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires_at),
            )
            conn.commit()
            conn.close()
        return token

    def validate_token(self, token: str) -> Optional[User]:
        """Validate session token. Returns User if valid, None if expired/invalid."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            conn.close()
            return None

        # Check expiry
        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > expires_at:
            conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
            return None

        user = self.get_user_by_id(row["user_id"], conn=conn)
        conn.close()
        return user

    def delete_token(self, token: str) -> None:
        """Delete a session token (logout)."""
        with self._lock:
            conn = self._connect()
            conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()

    def cleanup_expired_tokens(self) -> int:
        """Remove expired tokens. Returns count removed."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            conn = self._connect()
            cursor = conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
            conn.commit()
            count = cursor.rowcount
            conn.close()
        if count:
            logger.debug("Cleaned up %d expired session tokens", count)
        return count

    def get_internal_service_user(self) -> User:
        """Return a synthetic admin user for internal service-to-service calls."""
        return User(
            id=0,
            username="_service",
            display_name="Internal Service",
            is_admin=True,
        )

    def ensure_local_user(self) -> User:
        """Ensure the default local_user exists (for local mode). Returns the user."""
        user = self.get_user_by_username("local_user")
        if user:
            return user
        # Create with a random password (never used for login)
        return self.create_user(
            username="local_user",
            password=secrets.token_urlsafe(32),
            display_name="User",
            is_admin=True,
        )
