"""Tests for indexer API helper filters."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from src.indexer.api_server import IndexerAPIConfig, _get_user_search_filters


class _DummyAuthManager:
    def get_all_usernames(self) -> list[str]:
        return []


def _make_cfg_with_roots(tmp_path: Path, roots: list[tuple[str, int]]) -> IndexerAPIConfig:
    watcher_db = tmp_path / "watcher.db"
    conn = sqlite3.connect(str(watcher_db))
    conn.execute("CREATE TABLE roots (path TEXT, enabled INTEGER)")
    conn.executemany("INSERT INTO roots(path, enabled) VALUES (?, ?)", roots)
    conn.commit()
    conn.close()

    return IndexerAPIConfig(
        vector_db=tmp_path / "vectors.db",
        watcher_db=watcher_db,
        remote_mode=False,
    )


def test_empty_agent_root_selection_excludes_all_enabled_roots(tmp_path: Path):
    cfg = _make_cfg_with_roots(
        tmp_path,
        [("/docs/a", 1), ("/docs/b", 1), ("/docs/c", 0)],
    )
    user = SimpleNamespace(username="alice", knowledge_roots={"ask_hti_agent": []})

    exclude, inc_under, inc_roots = _get_user_search_filters(
        user=user,
        auth_mgr=_DummyAuthManager(),
        cfg=cfg,
        agent_name="ask_hti_agent",
    )

    assert set(exclude or []) == {"/docs/a", "/docs/b"}
    # Local mode: no include scoping
    assert inc_under is None
    assert inc_roots is None


def test_agent_root_subset_excludes_only_unselected_enabled_roots(tmp_path: Path):
    cfg = _make_cfg_with_roots(
        tmp_path,
        [("/docs/a", 1), ("/docs/b", 1), ("/docs/c", 0)],
    )
    user = SimpleNamespace(username="alice", knowledge_roots={"ask_hti_agent": ["/docs/a"]})

    exclude, inc_under, inc_roots = _get_user_search_filters(
        user=user,
        auth_mgr=_DummyAuthManager(),
        cfg=cfg,
        agent_name="ask_hti_agent",
    )

    assert set(exclude or []) == {"/docs/b"}
    assert inc_under is None
    assert inc_roots is None


def test_null_agent_root_selection_means_all_roots(tmp_path: Path):
    cfg = _make_cfg_with_roots(tmp_path, [("/docs/a", 1), ("/docs/b", 1)])
    user = SimpleNamespace(username="alice", knowledge_roots={"ask_hti_agent": None})

    exclude, inc_under, inc_roots = _get_user_search_filters(
        user=user,
        auth_mgr=_DummyAuthManager(),
        cfg=cfg,
        agent_name="ask_hti_agent",
    )

    assert exclude is None
    assert inc_under is None
    assert inc_roots is None


def test_remote_mode_include_scoping(tmp_path: Path):
    """In remote mode, include_under/include_roots scope to user's uploads + shared."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    cfg = IndexerAPIConfig(
        vector_db=tmp_path / "vectors.db",
        watcher_db=tmp_path / "watcher.db",
        remote_mode=True,
        uploads_dir=uploads,
    )
    user = SimpleNamespace(username="alice", knowledge_roots=None)

    exclude, inc_under, inc_roots = _get_user_search_filters(
        user=user,
        auth_mgr=_DummyAuthManager(),
        cfg=cfg,
    )

    assert exclude is None
    assert inc_under == str(uploads.resolve())
    assert set(inc_roots) == {
        str((uploads / "alice").resolve()),
        str((uploads / "shared_documents").resolve()),
    }
