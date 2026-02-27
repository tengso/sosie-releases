"""
ADK API Server launcher with database session service.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_app_data_dir() -> Path:
    """Get platform-specific application data directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    
    app_dir = base / "Sosie"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def start_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    session_db: Optional[str] = None,
    agents_dir: Optional[str] = None,
):
    """
    Start the ADK API server with database session service.
    
    Args:
        host: Server host address
        port: Server port
        session_db: Path to session database (SQLite)
        agents_dir: Path to agents directory
    """
    import subprocess
    
    # Determine agents directory
    if agents_dir is None:
        agents_dir = str(Path(__file__).parent.parent / "agents")
    
    # Determine session database path
    if session_db is None:
        session_db = str(get_app_data_dir() / "sessions.db")
    
    # Ensure data directory exists
    session_db_path = Path(session_db)
    session_db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set environment variables for ADK
    env = os.environ.copy()
    
    # Set default log level to INFO for noisy libraries
    env.setdefault("LITELLM_LOG", "WARNING")

    # Configure database session service
    # ADK uses async SQLite driver
    db_url = f"sqlite+aiosqlite:///{session_db_path.resolve()}"
    
    logger.info(f"Starting ADK API server on {host}:{port}")
    logger.info(f"Agents directory: {agents_dir}")
    logger.info(f"Session database: {session_db_path.resolve()}")
    
    # Build command
    cmd = [
        sys.executable, "-m", "google.adk.cli",
        "api_server",
        "--host", host,
        "--port", str(port),
        "--session_service_uri", db_url,
        "--memory_service_uri", "mem0://",
        agents_dir,
    ]
    
    try:
        # Run the server
        subprocess.run(cmd, env=env, check=True)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except subprocess.CalledProcessError as e:
        logger.error(f"Server exited with error: {e}")
        sys.exit(1)
    except FileNotFoundError:
        logger.error("google-adk not installed. Run: pip install google-adk aiosqlite")
        sys.exit(1)
