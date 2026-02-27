"""
Application settings persistence via SQLite key-value table in watcher.db.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Embedding model presets: model_id -> {dimensions, api_base, api_key_env}
EMBEDDING_PRESETS: Dict[str, Dict[str, Any]] = {
    "text-embedding-3-large": {
        "dimensions": 3072,
        "api_base": None,
        "api_key_env": "OPENAI_API_KEY",
        "batch_size": 100,
    },
    "text-embedding-v4": {
        "dimensions": 1024,
        "api_base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "batch_size": 10,
    },
}

# Agent model presets: model_id -> {display_name, api_key_env}
# Model IDs use LiteLLM provider prefixes (e.g. openai/, dashscope/)
AGENT_MODEL_PRESETS: Dict[str, Dict[str, Any]] = {
    "openai/gpt-4.1": {
        "display_name": "GPT-4.1",
        "api_key_env": "OPENAI_API_KEY",
    },
    "openai/gpt-5.2": {
        "display_name": "GPT-5.2",
        "api_key_env": "OPENAI_API_KEY",
    },
    "openai/gpt-5.2-mini": {
        "display_name": "GPT-5.2-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "dashscope/qwen3-max": {
        "display_name": "Qwen3-Max",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
}

# Default values
DEFAULT_AGENT_MODEL = "dashscope/qwen3-max"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"


class SettingsManager:
    """Manages application settings stored in watcher.db."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a setting value by key."""
        with self._connect() as conn:
            self._ensure_table(conn)
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set(self, key: str, value: Optional[str]) -> None:
        """Set a setting value."""
        with self._connect() as conn:
            self._ensure_table(conn)
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )

    def get_all(self) -> Dict[str, str]:
        """Get all settings as a dict."""
        with self._connect() as conn:
            self._ensure_table(conn)
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {row["key"]: row["value"] for row in rows}

    # --- High-level model settings ---

    def get_agent_model(self) -> str:
        model = self.get("agent_model", DEFAULT_AGENT_MODEL) or DEFAULT_AGENT_MODEL
        if model not in AGENT_MODEL_PRESETS:
            return DEFAULT_AGENT_MODEL
        return model

    def set_agent_model(self, model_id: str) -> None:
        self.set("agent_model", model_id)

    def get_embedding_model(self) -> str:
        return self.get("embedding_model", DEFAULT_EMBEDDING_MODEL) or DEFAULT_EMBEDDING_MODEL

    def set_embedding_model(self, model_id: str) -> None:
        self.set("embedding_model", model_id)

    def get_agent_config_overrides(self) -> Dict[str, Any]:
        """Get agent config values derived from the selected model preset."""
        model = self.get_agent_model()
        preset = AGENT_MODEL_PRESETS.get(model, AGENT_MODEL_PRESETS[DEFAULT_AGENT_MODEL])

        return {
            "model_id": model,
            "api_key_env": preset.get("api_key_env", "OPENAI_API_KEY"),
        }

    def get_embedding_config_overrides(self) -> Dict[str, Any]:
        """Get embedding config values derived from the selected model preset."""
        model = self.get_embedding_model()
        preset = EMBEDDING_PRESETS.get(model, EMBEDDING_PRESETS[DEFAULT_EMBEDDING_MODEL])

        return {
            "model_id": model,
            "dimensions": preset["dimensions"],
            "api_base": preset.get("api_base"),
            "api_key_env": preset.get("api_key_env", "OPENAI_API_KEY"),
            "batch_size": preset.get("batch_size", 100),
        }

    def get_models_info(self) -> Dict[str, Any]:
        """Get current model settings and available presets for the API."""
        emb_overrides = self.get_embedding_config_overrides()
        return {
            "agent_model": self.get_agent_model(),
            "embedding_model": emb_overrides["model_id"],
            "embedding_dimensions": emb_overrides["dimensions"],
            "embedding_api_base": emb_overrides["api_base"],
            "embedding_api_key_env": emb_overrides["api_key_env"],
            "agent_model_presets": [
                {"model_id": mid, "display_name": info["display_name"]}
                for mid, info in AGENT_MODEL_PRESETS.items()
            ],
            "embedding_presets": [
                {
                    "model_id": mid,
                    "dimensions": info["dimensions"],
                    "api_base": info["api_base"],
                    "api_key_env": info["api_key_env"],
                }
                for mid, info in EMBEDDING_PRESETS.items()
            ],
        }
