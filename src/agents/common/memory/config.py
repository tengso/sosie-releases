import os
import sys
from pathlib import Path


def _get_data_dir() -> Path:
    """Get platform-specific application data directory for Sosie."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    app_dir = base / "Sosie"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_memory_config() -> dict:
    """
    Returns:
        Mem0 configuration dictionary
    """
    api_key = os.getenv('DASHSCOPE_API_KEY', None)
    if api_key is None:
        raise ValueError('DASHSCOPE_API_KEY environment variable is not set')
    url_base = os.getenv('DASHSCOPE_API_BASE', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1')

    llm_model = os.getenv('MEM0_MODEL', 'qwen3-max')
    emb_model = os.getenv('MEM0_EMBEDDING_MODEL', 'text-embedding-v4')

    chroma_path = str(_get_data_dir() / "chroma_db")

    return {
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "memory",
                "path": chroma_path,
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": llm_model,
                "openai_base_url": url_base,
                "temperature": 0.1,
                "api_key": api_key,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": emb_model,
                "openai_base_url": url_base,
                "api_key": api_key,
            },
        },
        "version": "v1.1",
    }
