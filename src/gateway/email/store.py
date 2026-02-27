"""
SQLite persistence for the email gateway.

Tables: authorized_users, conversations, sync_state, message_log.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import ConversationRow

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS authorized_users (
    email           TEXT PRIMARY KEY,
    display_name    TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Demux keys
    conversation_id TEXT UNIQUE,
    relay_token     TEXT UNIQUE,

    -- Classification
    type            TEXT NOT NULL,
    owner_email     TEXT NOT NULL,
    state           TEXT DEFAULT 'active',

    -- Agent session fields
    agent_name      TEXT,
    adk_session_id  TEXT,
    adk_user_id     TEXT,

    -- Relay fields
    relay_peer_id   INTEGER REFERENCES conversations(id),
    relay_target_email TEXT,

    -- Timestamps
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Last Exchange message_id for threading
    last_message_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_conv_owner ON conversations(owner_email, state);

CREATE TABLE IF NOT EXISTS sync_state (
    folder_id       TEXT PRIMARY KEY,
    item_sync_state TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS message_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    direction       TEXT NOT NULL,
    conversation_id TEXT,
    sender_email    TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    subject         TEXT,
    body_preview    TEXT,
    action          TEXT,
    has_attachments BOOLEAN DEFAULT FALSE,
    exchange_msg_id TEXT,
    processed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_log_conv ON message_log(conversation_id);
CREATE INDEX IF NOT EXISTS idx_log_sender ON message_log(sender_email, processed_at);
"""


def _row_to_conversation(row: sqlite3.Row) -> ConversationRow:
    """Convert a sqlite3.Row to a ConversationRow dataclass."""
    return ConversationRow(
        id=row["id"],
        conversation_id=row["conversation_id"],
        relay_token=row["relay_token"],
        type=row["type"],
        owner_email=row["owner_email"],
        state=row["state"],
        agent_name=row["agent_name"],
        adk_session_id=row["adk_session_id"],
        adk_user_id=row["adk_user_id"],
        relay_peer_id=row["relay_peer_id"],
        relay_target_email=row["relay_target_email"],
        created_at=row["created_at"],
        last_active=row["last_active"],
        last_message_id=row["last_message_id"],
    )


class ConversationStore:
    """SQLite-backed store for gateway conversations and audit logs."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ── Authorized users ─────────────────────────────────────────

    def is_authorized(self, email: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM authorized_users WHERE email = ? AND is_active = TRUE",
            (email.lower(),),
        ).fetchone()
        return row is not None

    def add_authorized_user(self, email: str, display_name: Optional[str] = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO authorized_users (email, display_name) VALUES (?, ?)",
            (email.lower(), display_name),
        )
        self._conn.commit()

    def remove_authorized_user(self, email: str) -> None:
        self._conn.execute(
            "UPDATE authorized_users SET is_active = FALSE WHERE email = ?",
            (email.lower(),),
        )
        self._conn.commit()

    def list_authorized_users(self) -> list:
        rows = self._conn.execute(
            "SELECT email, display_name FROM authorized_users WHERE is_active = TRUE"
        ).fetchall()
        return [{"email": r["email"], "display_name": r["display_name"]} for r in rows]

    # ── Conversation lookup (demux) ──────────────────────────────

    def get_by_conversation_id(self, conversation_id: str) -> Optional[ConversationRow]:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ? AND state = 'active'",
            (conversation_id,),
        ).fetchone()
        return _row_to_conversation(row) if row else None

    def get_by_relay_token(self, token: str) -> Optional[ConversationRow]:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE relay_token = ? AND state = 'active'",
            (token,),
        ).fetchone()
        return _row_to_conversation(row) if row else None

    def get_by_id(self, conv_id: int) -> Optional[ConversationRow]:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
        return _row_to_conversation(row) if row else None

    # ── Conversation creation ────────────────────────────────────

    def create_agent_conversation(
        self,
        conversation_id: str,
        owner_email: str,
        agent_name: str,
        adk_session_id: str,
        adk_user_id: str,
    ) -> int:
        """Create an agent conversation. Returns the new row id."""
        cur = self._conn.execute(
            """INSERT INTO conversations
               (conversation_id, type, owner_email, agent_name, adk_session_id, adk_user_id)
               VALUES (?, 'agent', ?, ?, ?, ?)""",
            (conversation_id, owner_email.lower(), agent_name, adk_session_id, adk_user_id),
        )
        self._conn.commit()
        return cur.lastrowid

    def create_relay_pair(
        self,
        initiator_conversation_id: str,
        initiator_email: str,
        target_email: str,
        relay_token: str,
    ) -> tuple:
        """Create a linked relay pair. Returns (initiator_id, target_id)."""
        cur_init = self._conn.execute(
            """INSERT INTO conversations
               (conversation_id, type, owner_email, relay_target_email)
               VALUES (?, 'relay_initiator', ?, ?)""",
            (initiator_conversation_id, initiator_email.lower(), target_email.lower()),
        )
        initiator_id = cur_init.lastrowid

        cur_tgt = self._conn.execute(
            """INSERT INTO conversations
               (conversation_id, relay_token, type, owner_email, relay_target_email)
               VALUES (NULL, ?, 'relay_target', ?, ?)""",
            (relay_token, target_email.lower(), initiator_email.lower()),
        )
        target_id = cur_tgt.lastrowid

        # Link peers
        self._conn.execute(
            "UPDATE conversations SET relay_peer_id = ? WHERE id = ?",
            (target_id, initiator_id),
        )
        self._conn.execute(
            "UPDATE conversations SET relay_peer_id = ? WHERE id = ?",
            (initiator_id, target_id),
        )
        self._conn.commit()
        return initiator_id, target_id

    # ── Conversation updates ─────────────────────────────────────

    def touch(self, conv_id: int, last_message_id: Optional[str] = None) -> None:
        """Update last_active and optionally last_message_id."""
        now = datetime.utcnow().isoformat()
        if last_message_id:
            self._conn.execute(
                "UPDATE conversations SET last_active = ?, last_message_id = ? WHERE id = ?",
                (now, last_message_id, conv_id),
            )
        else:
            self._conn.execute(
                "UPDATE conversations SET last_active = ? WHERE id = ?",
                (now, conv_id),
            )
        self._conn.commit()

    def backfill_conversation_id(self, conv_id: int, conversation_id: str) -> None:
        """Set conversation_id on a relay_target row after first reply."""
        self._conn.execute(
            "UPDATE conversations SET conversation_id = ? WHERE id = ?",
            (conversation_id, conv_id),
        )
        self._conn.commit()

    def close_conversation(self, conv_id: int) -> None:
        self._conn.execute(
            "UPDATE conversations SET state = 'closed' WHERE id = ?",
            (conv_id,),
        )
        self._conn.commit()

    # ── Sync state ───────────────────────────────────────────────

    def get_sync_state(self, folder_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT item_sync_state FROM sync_state WHERE folder_id = ?",
            (folder_id,),
        ).fetchone()
        return row["item_sync_state"] if row else None

    def set_sync_state(self, folder_id: str, state: str) -> None:
        self._conn.execute(
            """INSERT INTO sync_state (folder_id, item_sync_state, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(folder_id) DO UPDATE SET item_sync_state = ?, updated_at = ?""",
            (folder_id, state, datetime.utcnow().isoformat(), state, datetime.utcnow().isoformat()),
        )
        self._conn.commit()

    # ── Message log (compliance audit) ───────────────────────────

    def log_message(
        self,
        direction: str,
        sender_email: str,
        recipient_email: str,
        subject: Optional[str] = None,
        body_preview: Optional[str] = None,
        conversation_id: Optional[str] = None,
        action: Optional[str] = None,
        has_attachments: bool = False,
        exchange_msg_id: Optional[str] = None,
    ) -> None:
        preview = body_preview[:500] if body_preview else None
        self._conn.execute(
            """INSERT INTO message_log
               (direction, conversation_id, sender_email, recipient_email,
                subject, body_preview, action, has_attachments, exchange_msg_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (direction, conversation_id, sender_email.lower(), recipient_email.lower(),
             subject, preview, action, has_attachments, exchange_msg_id),
        )
        self._conn.commit()
