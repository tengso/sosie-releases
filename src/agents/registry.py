"""
Agent registry — metadata for all available agents.

This module discovers agent packages from ``src/agents`` without importing
ADK agent modules, so it remains safe to use from the indexer API server.
"""

import ast
import copy
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Default agent avatar SVGs (data URIs)
_AVATAR_QA = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 80'%3E"
    "%3Crect width='80' height='80' rx='20' fill='%23172554'/%3E"
    "%3Ccircle cx='40' cy='36' r='18' fill='%233b82f6' opacity='0.25'/%3E"
    "%3Cpath d='M28 30h24a3 3 0 013 3v12a3 3 0 01-3 3H38l-6 5v-5h-4a3 3 0 01-3-3V33a3 3 0 013-3z' "
    "fill='%2360a5fa'/%3E%3C/svg%3E"
)
_AVATAR_RESEARCH = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 80'%3E"
    "%3Crect width='80' height='80' rx='20' fill='%233b0764'/%3E"
    "%3Ccircle cx='40' cy='36' r='18' fill='%23a855f7' opacity='0.25'/%3E"
    "%3Cpath d='M30 26h20a2 2 0 012 2v24a2 2 0 01-2 2H30a2 2 0 01-2-2V28a2 2 0 012-2z' "
    "fill='%23c084fc'/%3E"
    "%3Cpath d='M34 34h12M34 39h12M34 44h8' stroke='%233b0764' stroke-width='2' stroke-linecap='round'/%3E"
    "%3C/svg%3E"
)

_BUILTIN_ORDER: List[str] = [
    "doc_qa_agent",
    "deep_research_agent",
]

_COMMON_ACRONYMS = {"ai", "api", "hti", "llm", "mcp", "nlp", "pdf", "qa", "rag", "ui", "ux"}

_BUILTIN_AGENT_METADATA: Dict[str, Dict[str, Any]] = {
    "doc_qa_agent": {
        "name": "doc_qa_agent",
        "display_name": "Document Q&A",
        "description": "Answers questions based on indexed documents using semantic search. "
        "Always searches first, cites sources, and handles missing information gracefully.",
        "category": "chat",
        "icon": "message-square",
        "color": "blue",
        "avatar_url": _AVATAR_QA,
        "features": {
            "has_sources_panel": True,
            "has_progress_panel": False,
            "has_depth_selector": False,
        },
        "tools": [
            "search_chunks",
            "list_available_documents",
            "keyword_search",
            "get_user_contact",
        ],
        "default_model": "dashscope/qwen3-max",
        "model_env": "SOSIE_AGENT_MODEL",
    },
    "deep_research_agent": {
        "name": "deep_research_agent",
        "display_name": "Deep Research",
        "description": "Conducts thorough research across indexed documents with citations. "
        "Supports quick, standard, and deep research depths with structured reports.",
        "category": "research",
        "icon": "book-open",
        "color": "purple",
        "avatar_url": _AVATAR_RESEARCH,
        "features": {
            "has_sources_panel": False,
            "has_progress_panel": True,
            "has_depth_selector": True,
        },
        "tools": [
            "search_documents",
            "search_chunks",
            "list_available_documents",
            "multi_query_search",
            "get_user_contact",
        ],
        "default_model": "dashscope/qwen3-max",
        "model_env": "SOSIE_AGENT_MODEL",
    },
}


def _agents_dir() -> Path:
    return Path(__file__).resolve().parent


def _display_name_from_agent_name(agent_name: str) -> str:
    base = agent_name[:-6] if agent_name.endswith("_agent") else agent_name
    words: List[str] = []
    for token in base.split("_"):
        if not token:
            continue
        lower = token.lower()
        words.append(token.upper() if lower in _COMMON_ACRONYMS else token.capitalize())
    return " ".join(words) if words else agent_name


def _first_docstring_line(docstring: str) -> str:
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _parse_agent_module(agent_file: Path) -> Tuple[bool, str, List[str]]:
    try:
        source = agent_file.read_text(encoding="utf-8")
    except Exception:
        return False, "", []

    try:
        module = ast.parse(source)
    except SyntaxError:
        return False, "", []

    has_root_agent = False
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "root_agent":
                    has_root_agent = True
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "root_agent":
                has_root_agent = True
        if has_root_agent:
            break

    docstring = ast.get_docstring(module) or ""
    tools: List[str] = []
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == "src.agents.common":
            for alias in node.names:
                if alias.name != "*" and alias.name not in tools:
                    tools.append(alias.name)

    return has_root_agent, docstring, tools


def _default_category(agent_name: str, docstring: str) -> str:
    haystack = f"{agent_name} {docstring}".lower()
    return "research" if "research" in haystack else "chat"


def _default_features(category: str) -> Dict[str, bool]:
    if category == "research":
        return {
            "has_sources_panel": False,
            "has_progress_panel": True,
            "has_depth_selector": True,
        }
    return {
        "has_sources_panel": True,
        "has_progress_panel": False,
        "has_depth_selector": False,
    }


def _default_agent_metadata(agent_name: str, docstring: str, tools: List[str]) -> Dict[str, Any]:
    category = _default_category(agent_name, docstring)
    first_line = _first_docstring_line(docstring)
    if first_line:
        description = first_line
    elif category == "research":
        description = "Conducts research across indexed documents."
    else:
        description = "Answers questions based on indexed documents."

    if category == "research":
        icon = "book-open"
        color = "purple"
        avatar_url = _AVATAR_RESEARCH
    else:
        icon = "message-square"
        color = "blue"
        avatar_url = _AVATAR_QA

    return {
        "name": agent_name,
        "display_name": _display_name_from_agent_name(agent_name),
        "description": description,
        "category": category,
        "icon": icon,
        "color": color,
        "avatar_url": avatar_url,
        "features": _default_features(category),
        "tools": tools,
        "default_model": "dashscope/qwen3-max",
        "model_env": "SOSIE_AGENT_MODEL",
    }


def _sort_agents(agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order = {name: idx for idx, name in enumerate(_BUILTIN_ORDER)}
    return sorted(
        agents,
        key=lambda agent: (
            order.get(agent["name"], len(order)),
            agent["display_name"].lower(),
        ),
    )


def _discover_agents() -> List[Dict[str, Any]]:
    agents_dir = _agents_dir()
    discovered: List[Dict[str, Any]] = []

    try:
        children = sorted(agents_dir.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return []

    for package_dir in children:
        if not package_dir.is_dir():
            continue
        if package_dir.name.startswith("_") or package_dir.name in {"common", "__pycache__"}:
            continue

        init_file = package_dir / "__init__.py"
        agent_file = package_dir / "agent.py"
        if not init_file.exists() or not agent_file.exists():
            continue

        has_root_agent, docstring, tools = _parse_agent_module(agent_file)
        if not has_root_agent:
            continue

        known = _BUILTIN_AGENT_METADATA.get(package_dir.name)
        if known is not None:
            entry = copy.deepcopy(known)
        else:
            entry = _default_agent_metadata(package_dir.name, docstring, tools)
        discovered.append(entry)

    return _sort_agents(discovered)


def get_agents() -> List[Dict[str, Any]]:
    """Return discovered agents with resolved model info."""
    discovered = _discover_agents()
    if not discovered:
        discovered = _sort_agents([copy.deepcopy(meta) for meta in _BUILTIN_AGENT_METADATA.values()])

    result: List[Dict[str, Any]] = []
    for agent in discovered:
        entry = copy.deepcopy(agent)
        model_env = str(entry.get("model_env") or "SOSIE_AGENT_MODEL")
        default_model = str(entry.get("default_model") or "dashscope/qwen3-max")
        entry["model_env"] = model_env
        entry["default_model"] = default_model
        entry["model"] = os.environ.get(model_env, default_model)
        result.append(entry)
    return result
