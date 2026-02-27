"""Tests for dynamic agent registry discovery."""

from pathlib import Path

import src.agents.registry as registry


def _make_agent_package(base: Path, name: str, agent_source: str) -> None:
    pkg = base / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .agent import root_agent\n", encoding="utf-8")
    (pkg / "agent.py").write_text(agent_source, encoding="utf-8")


def test_get_agents_discovers_valid_agent_packages(monkeypatch, tmp_path):
    _make_agent_package(
        tmp_path,
        "ask_hti_agent",
        '''
"""HTI firm policies Agent."""

from src.agents.common import search_chunks, keyword_search

root_agent = object()
''',
    )

    _make_agent_package(
        tmp_path,
        "broken_agent",
        '''
"""Broken agent missing root assignment."""

from src.agents.common import search_chunks
''',
    )

    # Non-agent support directory should be ignored
    common = tmp_path / "common"
    common.mkdir()
    (common / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(registry, "_agents_dir", lambda: tmp_path)

    agents = registry.get_agents()
    names = {agent["name"] for agent in agents}

    assert "ask_hti_agent" in names
    assert "broken_agent" not in names

    ask_hti = next(agent for agent in agents if agent["name"] == "ask_hti_agent")
    assert ask_hti["display_name"] == "Ask HTI"
    assert ask_hti["description"] == "HTI firm policies Agent."
    assert ask_hti["category"] == "chat"
    assert ask_hti["tools"] == ["search_chunks", "keyword_search"]
    assert ask_hti["features"]["has_sources_panel"] is True


def test_get_agents_falls_back_to_builtin_metadata_when_discovery_fails(monkeypatch):
    monkeypatch.setattr(registry, "_agents_dir", lambda: Path("/path/that/does/not/exist"))
    monkeypatch.setenv("SOSIE_AGENT_MODEL", "test-model")

    agents = registry.get_agents()
    names = {agent["name"] for agent in agents}

    assert "doc_qa_agent" in names
    assert "deep_research_agent" in names
    assert all(agent["model"] == "test-model" for agent in agents)

    doc_qa = next(agent for agent in agents if agent["name"] == "doc_qa_agent")
    deep_research = next(agent for agent in agents if agent["name"] == "deep_research_agent")

    assert "get_user_contact" in doc_qa["tools"]
    assert "get_user_contact" in deep_research["tools"]
