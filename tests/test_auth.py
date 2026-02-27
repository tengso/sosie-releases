"""Tests for auth manager user profile fields."""

import sqlite3

import pytest

from src.indexer.auth import AuthManager


def test_create_user_persists_email(tmp_path):
    db_path = tmp_path / "auth.db"
    auth = AuthManager(db_path)

    user = auth.create_user(
        username="alice",
        password="secure-password",
        display_name="Alice",
        email="alice@example.com",
    )

    assert user.email == "alice@example.com"

    fetched = auth.get_user_by_username("alice")
    assert fetched is not None
    assert fetched.email == "alice@example.com"


def test_update_user_can_set_and_clear_email(tmp_path):
    db_path = tmp_path / "auth.db"
    auth = AuthManager(db_path)

    user = auth.create_user(
        username="bob",
        password="secure-password",
        display_name="Bob",
    )

    updated = auth.update_user(user.id, email="bob@example.com")
    assert updated is not None
    assert updated.email == "bob@example.com"

    cleared = auth.update_user(user.id, email=None)
    assert cleared is not None
    assert cleared.email is None


def test_create_user_rejects_invalid_email(tmp_path):
    db_path = tmp_path / "auth.db"
    auth = AuthManager(db_path)

    with pytest.raises(ValueError, match="Invalid email address"):
        auth.create_user(
            username="charlie",
            password="secure-password",
            display_name="Charlie",
            email="not-an-email",
        )


def test_update_user_rejects_invalid_email(tmp_path):
    db_path = tmp_path / "auth.db"
    auth = AuthManager(db_path)

    user = auth.create_user(
        username="dana",
        password="secure-password",
        display_name="Dana",
    )

    with pytest.raises(ValueError, match="Invalid email address"):
        auth.update_user(user.id, email="still-not-an-email")


def test_existing_users_table_is_migrated_with_email_column(tmp_path):
    db_path = tmp_path / "auth.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            display_name TEXT NOT NULL,
            avatar_url TEXT,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE auth_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    AuthManager(db_path)

    conn = sqlite3.connect(db_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    conn.close()

    assert "email" in columns
