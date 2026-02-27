#!/usr/bin/env python3
"""
Sosie Desktop Application Launcher.

This is the main entry point for the packaged desktop application.
It starts all backend services and opens the web UI in a native window.
"""

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

def setup_logging() -> Path:
    """Configure logging with file output to ~/.myai for debugging."""
    log_dir = Path.home() / ".myai"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "sosie.log"
    
    # Create formatters
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # File handler - DEBUG level for detailed logs
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    
    # Console handler - INFO level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return log_file

# Set up logging
LOG_FILE = setup_logging()
logger = logging.getLogger("sosie")


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


def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and PyInstaller."""
    if getattr(sys, 'frozen', False):
        # Running in PyInstaller bundle
        base_path = Path(sys._MEIPASS)  # type: ignore
    else:
        # Running in development
        base_path = Path(__file__).parent
    
    return base_path / relative_path


class ServiceManager:
    """Manages backend services lifecycle."""
    
    def __init__(self, data_dir: Path, remote_mode: bool = False, indexer_port: int = 8001, agent_port: int = 8000):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.remote_mode = remote_mode
        
        # Generate internal service token for agent→indexer calls
        import secrets
        service_token = secrets.token_hex(32)
        os.environ["SOSIE_SERVICE_TOKEN"] = service_token
        
        self.watcher_db = data_dir / "watcher.db"
        self.vector_db = data_dir / "vectors.db"
        self.session_db = data_dir / "sessions.db"

        # Make auth DB path available to ADK tools (e.g., get_user_contact)
        os.environ["SOSIE_AUTH_DB_PATH"] = str((data_dir / "auth.db").resolve())
        
        # Managed uploads directory (used in remote mode)
        self.uploads_dir = data_dir / "uploads"
        if remote_mode:
            self.uploads_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Remote mode: uploads directory at {self.uploads_dir}")
        
        self._indexer = None
        self._indexer_api_thread: Optional[threading.Thread] = None
        self._agent_server_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        
        # Ports
        self.indexer_port = indexer_port
        self.agent_port = agent_port
    
    def _load_model_settings(self):
        """Load model settings from DB and set env vars."""
        from src.indexer.settings import SettingsManager
        sm = SettingsManager(self.watcher_db)

        # Set agent model env var (LiteLLM routes via provider prefix)
        agent_model = sm.get_agent_model()
        os.environ["SOSIE_AGENT_MODEL"] = agent_model
        logger.info(f"Agent model: {agent_model}")

        # Return embedding overrides for IndexerConfig
        emb = sm.get_embedding_config_overrides()
        logger.info(f"Embedding model: {emb['model_id']} (dims={emb['dimensions']})")
        return emb

    def start_indexer_service(self):
        """Start the indexer process with API server."""
        from src.indexer import IndexerProcess, IndexerConfig, EmbeddingConfig, ChunkingConfig
        
        logger.info("Starting indexer service...")
        
        # Set env vars so IndexerProcess picks up the configured port/host
        os.environ["INDEXER_API_PORT"] = str(self.indexer_port)
        if self.remote_mode:
            os.environ["INDEXER_API_HOST"] = "0.0.0.0"
        
        # Load persisted model settings
        emb_overrides = self._load_model_settings()
        
        # Get path to React frontend
        web_dist = get_resource_path("web/dist")
        logger.info(f"Web dist path: {web_dist}, exists: {web_dist.exists()}")
        
        config = IndexerConfig(
            watcher_db_path=self.watcher_db,
            vector_db_path=self.vector_db,
            web_dist_path=web_dist if web_dist.exists() else None,
            remote_mode=self.remote_mode,
            uploads_dir=self.uploads_dir if self.remote_mode else None,
            embedding=EmbeddingConfig(
                model_id=emb_overrides["model_id"],
                dimensions=emb_overrides["dimensions"],
                api_base=emb_overrides["api_base"],
                api_key_env=emb_overrides["api_key_env"],
                batch_size=emb_overrides["batch_size"],
                https_proxy=os.environ.get("HTTPS_PROXY"),
            ),
            chunking=ChunkingConfig(),
        )
        
        self._indexer = IndexerProcess(config=config)
        self._indexer.start_async()
        
        # In remote mode, auto-register uploads dir as a document root
        if self.remote_mode:
            try:
                self._indexer.add_root(self.uploads_dir)
                logger.info(f"Auto-registered uploads root: {self.uploads_dir}")
            except Exception as e:
                logger.debug(f"Uploads root registration: {e}")
        
        logger.info("Indexer service started")
    
    def start_agent_service(self):
        """Start the agent API server."""
        logger.info("Starting agent service...")
        
        def run_agent_server():
            agents_dir = str(get_resource_path("src/agents"))
            db_url = f"sqlite+aiosqlite:///{self.session_db.resolve()}"
            
            # Suppress noisy LiteLLM debug logging
            os.environ.setdefault("LITELLM_LOG", "WARNING")
            logging.getLogger("LiteLLM").setLevel(logging.WARNING)
            logging.getLogger("litellm").setLevel(logging.WARNING)
            
            try:
                # Pre-create session tables to avoid race condition on fresh DB
                import asyncio
                from google.adk.sessions.database_session_service import DatabaseSessionService

                async def _init_session_tables():
                    svc = DatabaseSessionService(db_url=db_url)
                    await svc.list_sessions(app_name="_init", user_id="_init")
                    await svc.db_engine.dispose()

                asyncio.run(_init_session_tables())
                logger.info("Session database tables initialized")

                # Import and run ADK server directly (works in frozen app)
                from google.adk.cli import fast_api
                import uvicorn
                
                # Create the FastAPI app from ADK
                app = fast_api.get_fast_api_app(
                    agents_dir=agents_dir,
                    session_service_uri=db_url,
                    memory_service_uri="mem0://",
                    allow_origins=["*"],
                    web=True,
                    host="0.0.0.0",
                    port=self.agent_port,
                )
                
                # Run with uvicorn
                uvicorn.run(
                    app,
                    host="0.0.0.0",
                    port=self.agent_port,
                    log_level="warning",
                )
            except ImportError as e:
                logger.warning(f"ADK not available, agent service disabled: {e}")
            except Exception as e:
                logger.error(f"Agent server error: {e}")
        
        self._agent_server_thread = threading.Thread(target=run_agent_server, daemon=True)
        self._agent_server_thread.start()
        
        # Wait for agent server to start
        time.sleep(2)
        logger.info(f"Agent service started on port {self.agent_port}")
    
    def start_all(self):
        """Start all backend services."""
        self.start_indexer_service()
        self.start_agent_service()
    
    def stop_all(self):
        """Stop all backend services."""
        logger.info("Stopping services...")
        self._shutdown_event.set()
        
        if self._indexer:
            self._indexer.stop()
        
        logger.info("Services stopped")


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Wait for a server to become available."""
    import urllib.request
    import urllib.error
    
    last_error = None
    start = time.time()
    attempts = 0
    while time.time() - start < timeout:
        attempts += 1
        try:
            resp = urllib.request.urlopen(url, timeout=2)
            logger.debug(f"Health check OK (attempt {attempts}, {resp.status})")
            return True
        except urllib.error.HTTPError as e:
            # Server is up but returned an error (e.g. 401 auth required)
            last_error = f"HTTP {e.code} {e.reason}"
            if attempts == 1:
                logger.warning(f"Health check at {url} returned {last_error}")
            time.sleep(0.5)
        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            last_error = str(e)
            time.sleep(0.5)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            time.sleep(0.5)
    
    elapsed = time.time() - start
    logger.error(
        f"Health check failed after {elapsed:.1f}s ({attempts} attempts). "
        f"URL: {url}, last error: {last_error}"
    )
    return False


def run_gui(service_manager: ServiceManager):
    """Run the application with PyWebView GUI."""
    try:
        import webview
    except ImportError:
        logger.error("PyWebView not installed. Install with: pip install pywebview")
        logger.info("Falling back to browser mode...")
        run_browser(service_manager)
        return
    
    # Serve React frontend from indexer server
    url = f"http://localhost:{service_manager.indexer_port}"
    
    logger.info(f"Opening UI at {url}")
    
    # Wait for backend to be ready
    if not wait_for_server(f"http://localhost:{service_manager.indexer_port}/api/dashboard/health"):
        logger.warning("Backend not ready, opening anyway...")
    
    # Create window
    window = webview.create_window(
        title="Sosie - Document Q&A",
        url=url,
        width=1280,
        height=800,
        min_size=(800, 600),
        confirm_close=True,
    )
    
    def on_closing():
        service_manager.stop_all()
        return True
    
    window.events.closing += on_closing
    
    # Start webview (blocks until window closed)
    webview.start()


def run_browser(service_manager: ServiceManager):
    """Run the application in browser mode (fallback)."""
    import webbrowser
    
    url = f"http://localhost:{service_manager.indexer_port}"
    
    # Wait for backend
    logger.info("Waiting for backend services...")
    if wait_for_server(f"http://localhost:{service_manager.indexer_port}/api/dashboard/health"):
        logger.info(f"Opening browser at {url}")
        webbrowser.open(url)
    else:
        logger.error("Backend failed to start")
        return
    
    # Keep running until Ctrl+C
    try:
        logger.info("Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        service_manager.stop_all()


def run_headless(data_dir: Path, remote_mode: bool = False, indexer_port: int = 8001, agent_port: int = 8000):
    """Run in headless mode (no GUI, just services)."""
    service_manager = ServiceManager(data_dir, remote_mode=remote_mode, indexer_port=indexer_port, agent_port=agent_port)
    shutting_down = False
    
    def signal_handler(signum, frame):
        nonlocal shutting_down
        if shutting_down:
            logger.info("Forcing immediate exit...")
            os._exit(1)
        shutting_down = True
        logger.info("Shutting down... (press Ctrl+C again to force)")
        service_manager.stop_all()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    service_manager.start_all()
    
    logger.info("Services running. Press Ctrl+C to stop.")
    logger.info(f"  Indexer API: http://localhost:{service_manager.indexer_port}")
    logger.info(f"  Agent API: http://localhost:{service_manager.agent_port}")
    
    while True:
        time.sleep(1)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Sosie - Document Q&A Application")
    parser.add_argument("--headless", action="store_true", help="Run without GUI")
    parser.add_argument("--browser", action="store_true", help="Open in browser instead of native window")
    parser.add_argument("--remote", action="store_true", help="Remote mode: bind 0.0.0.0, enable file uploads")
    parser.add_argument("--port", type=int, default=8001, help="Indexer API port (default: 8001)")
    parser.add_argument("--agent-port", type=int, default=8000, help="Agent API port (default: 8000)")
    parser.add_argument("--db-dir", type=str, help="Database directory (default: platform-specific app data dir)")
    args = parser.parse_args()
    
    # Load environment variables from .env file
    try:
        from dotenv import load_dotenv
        env_file = get_resource_path(".env")
        if env_file.exists():
            load_dotenv(env_file)
        else:
            load_dotenv()  # Try current directory
    except ImportError:
        pass
    
    # Determine data directory
    if args.db_dir:
        data_dir = Path(args.db_dir)
    else:
        data_dir = get_app_data_dir()
    
    logger.info(f"Data directory: {data_dir}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.debug(f"Python executable: {sys.executable}")
    logger.debug(f"Frozen: {getattr(sys, 'frozen', False)}")
    if getattr(sys, 'frozen', False):
        logger.debug(f"MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")
    
    if args.headless:
        run_headless(data_dir, remote_mode=args.remote, indexer_port=args.port, agent_port=args.agent_port)
    else:
        service_manager = ServiceManager(data_dir, remote_mode=args.remote, indexer_port=args.port, agent_port=args.agent_port)
        shutting_down = False
        
        def signal_handler(signum, frame):
            nonlocal shutting_down
            if shutting_down:
                logger.info("Forcing immediate exit...")
                os._exit(1)
            shutting_down = True
            logger.info("Shutting down... (press Ctrl+C again to force)")
            service_manager.stop_all()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        service_manager.start_all()
        
        if args.browser:
            run_browser(service_manager)
        else:
            run_gui(service_manager)


if __name__ == "__main__":
    main()
