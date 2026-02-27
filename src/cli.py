#!/usr/bin/env python3
"""
CLI for starting watcher and indexer processes.

Usage:
    python -m src.cli watcher --roots /path/to/folder1 /path/to/folder2
    python -m src.cli indexer --watcher-db watcher.db --vector-db vectors.db
    python -m src.cli all --roots /path/to/folder --db-dir ./data
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env from project root
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
    else:
        load_dotenv()
except ImportError:
    pass

from src.watcher import WatcherProcess, WatcherConfig
from src.indexer import IndexerProcess, IndexerConfig, EmbeddingConfig, ChunkingConfig


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cli")


class GracefulShutdown:
    """Handle graceful shutdown on SIGINT/SIGTERM."""
    
    def __init__(self):
        self.should_exit = False
        signal.signal(signal.SIGINT, self._handler)
        signal.signal(signal.SIGTERM, self._handler)
    
    def _handler(self, signum, frame):
        logger.info("Received shutdown signal, stopping...")
        self.should_exit = True


def cmd_watcher(args):
    """Run the file watcher process."""
    logger.info("Starting watcher process...")
    
    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = WatcherConfig(
        db_path=db_path,
        debounce_ms=args.debounce,
        batch_timeout_ms=args.batch_timeout,
        move_correlation_ms=args.move_correlation,
    )
    
    # Resolve root paths
    roots = [Path(r).resolve() for r in args.roots] if args.roots else []
    
    # Validate roots
    for root in roots:
        if not root.exists():
            logger.error(f"Root path does not exist: {root}")
            sys.exit(1)
        if not root.is_dir():
            logger.error(f"Root path is not a directory: {root}")
            sys.exit(1)
    
    shutdown = GracefulShutdown()
    
    with WatcherProcess(config=config, initial_roots=roots) as watcher:
        watcher.start_async()
        
        logger.info(f"Watcher running with {len(roots)} root(s)")
        for root in roots:
            logger.info(f"  - {root}")
        logger.info(f"Database: {db_path}")
        logger.info("Press Ctrl+C to stop")
        
        while not shutdown.should_exit:
            # Log stats periodically
            time.sleep(5)
            events = watcher.get_pending_events(max_count=100)
            if events:
                logger.info(f"Processed {len(events)} events")
                for event in events[:5]:
                    logger.debug(f"  {event.event_type.value}: {event.path}")
    
    logger.info("Watcher stopped")


def cmd_indexer(args):
    """Run the indexer process."""
    logger.info("Starting indexer process...")
    
    watcher_db = Path(args.watcher_db).resolve()
    vector_db = Path(args.vector_db).resolve()
    vector_db.parent.mkdir(parents=True, exist_ok=True)
    
    # Load persisted model settings from DB (if any)
    from src.indexer.settings import SettingsManager
    sm = SettingsManager(watcher_db)
    emb_overrides = sm.get_embedding_config_overrides()

    # CLI args override persisted settings only if explicitly provided
    emb_model = emb_overrides["model_id"]
    emb_dims = emb_overrides["dimensions"]
    emb_api_base = emb_overrides["api_base"]
    emb_api_key_env = emb_overrides["api_key_env"]
    if args.embedding_model != emb_model:
        # CLI explicitly overrides the DB-persisted model
        from src.indexer.settings import EMBEDDING_PRESETS as _EP
        cli_preset = _EP.get(args.embedding_model)
        if cli_preset:
            emb_model = args.embedding_model
            emb_dims = cli_preset["dimensions"]
            emb_api_base = cli_preset.get("api_base")
            emb_api_key_env = cli_preset.get("api_key_env", "OPENAI_API_KEY")

    # Check that the required API key is available
    emb_api_key = args.api_key or os.environ.get(emb_api_key_env)
    if not emb_api_key:
        logger.error(f"API key not provided. Set {emb_api_key_env} or use --api-key")
        sys.exit(1)

    # Set agent model env var for ADK agent modules
    agent_model = sm.get_agent_model()
    os.environ["SOSIE_AGENT_MODEL"] = agent_model
    logger.info(f"Agent model: {agent_model}")
    logger.info(f"Embedding model: {emb_model} (dims={emb_dims})")

    config = IndexerConfig(
        watcher_db_path=watcher_db,
        vector_db_path=vector_db,
        embedding=EmbeddingConfig(
            model_id=emb_model,
            dimensions=emb_dims,
            api_base=emb_api_base,
            api_key_env=emb_api_key_env,
            api_key=emb_api_key,
            batch_size=emb_overrides["batch_size"],
            https_proxy=args.proxy or os.environ.get("HTTPS_PROXY"),
        ),
        chunking=ChunkingConfig(
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        ),
    )
    
    shutdown = GracefulShutdown()
    
    with IndexerProcess(config=config) as indexer:
        indexer.start_async()
        
        logger.info(f"Indexer running")
        logger.info(f"  Watcher DB: {watcher_db}")
        logger.info(f"  Vector DB: {vector_db}")
        logger.info(f"  Embedding model: {args.embedding_model}")
        logger.info("Press Ctrl+C to stop")
        
        while not shutdown.should_exit:
            time.sleep(5)
            stats = indexer.get_stats()
            logger.debug(f"Stats: {stats['document_count']} docs, {stats['chunk_count']} chunks")
    
    logger.info("Indexer stopped")


def cmd_all(args):
    """Run both watcher and indexer processes."""
    logger.info("Starting watcher and indexer processes...")
    
    db_dir = Path(args.db_dir).resolve()
    db_dir.mkdir(parents=True, exist_ok=True)
    
    watcher_db = db_dir / "watcher.db"
    vector_db = db_dir / "vectors.db"
    
    # Resolve root paths
    roots = [Path(r).resolve() for r in args.roots] if args.roots else []
    
    # Validate roots
    for root in roots:
        if not root.exists():
            logger.error(f"Root path does not exist: {root}")
            sys.exit(1)
        if not root.is_dir():
            logger.error(f"Root path is not a directory: {root}")
            sys.exit(1)
    
    # Load persisted model settings from DB (if any)
    from src.indexer.settings import SettingsManager
    sm = SettingsManager(watcher_db)
    emb_overrides = sm.get_embedding_config_overrides()

    emb_model = emb_overrides["model_id"]
    emb_dims = emb_overrides["dimensions"]
    emb_api_base = emb_overrides["api_base"]
    emb_api_key_env = emb_overrides["api_key_env"]
    if args.embedding_model != emb_model:
        # CLI explicitly overrides the DB-persisted model
        from src.indexer.settings import EMBEDDING_PRESETS as _EP
        cli_preset = _EP.get(args.embedding_model)
        if cli_preset:
            emb_model = args.embedding_model
            emb_dims = cli_preset["dimensions"]
            emb_api_base = cli_preset.get("api_base")
            emb_api_key_env = cli_preset.get("api_key_env", "OPENAI_API_KEY")

    # Check that the required API key is available
    emb_api_key = args.api_key or os.environ.get(emb_api_key_env)
    if not emb_api_key:
        logger.error(f"API key not provided. Set {emb_api_key_env} or use --api-key")
        sys.exit(1)

    agent_model = sm.get_agent_model()
    os.environ["SOSIE_AGENT_MODEL"] = agent_model
    logger.info(f"Agent model: {agent_model}")
    logger.info(f"Embedding model: {emb_model} (dims={emb_dims})")

    indexer_config = IndexerConfig(
        watcher_db_path=watcher_db,
        vector_db_path=vector_db,
        embedding=EmbeddingConfig(
            model_id=emb_model,
            dimensions=emb_dims,
            api_base=emb_api_base,
            api_key_env=emb_api_key_env,
            api_key=emb_api_key,
            batch_size=emb_overrides["batch_size"],
            https_proxy=args.proxy or os.environ.get("HTTPS_PROXY"),
        ),
        chunking=ChunkingConfig(
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        ),
    )
    
    shutdown = GracefulShutdown()
    
    # Use IndexerProcess with built-in watcher (pass initial_roots)
    with IndexerProcess(config=indexer_config, initial_roots=roots) as indexer:
        indexer.start_async()
        
        # Wait for watcher to initialize
        time.sleep(1)
        
        logger.info(f"Database directory: {db_dir}")
        for root in roots:
            logger.info(f"  Watching: {root}")
        logger.info("Press Ctrl+C to stop")
        
        while not shutdown.should_exit:
            time.sleep(5)
            
            # Log indexer stats
            stats = indexer.get_stats()
            logger.debug(f"Indexed: {stats['document_count']} docs, {stats['chunk_count']} chunks")
    
    logger.info("All processes stopped")


def cmd_search(args):
    """Search indexed documents."""
    vector_db = Path(args.vector_db).resolve()
    
    if not vector_db.exists():
        logger.error(f"Vector database not found: {vector_db}")
        sys.exit(1)
    
    # Check API key for query embedding
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OpenAI API key not provided. Set OPENAI_API_KEY or use --api-key")
        sys.exit(1)
    
    config = IndexerConfig(
        watcher_db_path=Path("watcher.db"),  # Not used for search
        vector_db_path=vector_db,
        embedding=EmbeddingConfig(
            api_key=api_key,
            https_proxy=args.proxy or os.environ.get("HTTPS_PROXY"),
        ),
    )
    
    with IndexerProcess(config=config) as indexer:
        results = indexer.search(args.query, top_k=args.top_k)
        
        if not results:
            print("No results found.")
            return
        
        print(f"\nFound {len(results)} result(s):\n")
        
        for i, result in enumerate(results, 1):
            print(f"─── Result {i} (score: {result.score:.3f}) ───")
            print(f"File: {result.document_path}")
            print(f"Content:\n{result.chunk.content[:500]}...")
            print()


def cmd_stats(args):
    """Show indexer statistics."""
    vector_db = Path(args.vector_db).resolve()
    
    if not vector_db.exists():
        logger.error(f"Vector database not found: {vector_db}")
        sys.exit(1)
    
    from src.indexer.store import VectorStore
    from src.indexer.config import VectorStoreConfig
    
    config = VectorStoreConfig(db_path=vector_db)
    
    with VectorStore(config) as store:
        stats = store.get_stats()
        
        print("\n=== Indexer Statistics ===")
        print(f"Database: {stats['db_path']}")
        print(f"Documents: {stats['document_count']}")
        print(f"Chunks: {stats['chunk_count']}")
        print(f"Embeddings: {stats['embedding_count']}")
        print()


def _indexer_api_base(args) -> str:
    host = getattr(args, "api_host", "localhost")
    port = getattr(args, "api_port", 8001)
    return f"http://{host}:{port}"


def cmd_add_root(args):
    """Add a document root directory."""
    root = Path(args.root).resolve()
    
    if not root.exists():
        logger.error(f"Root path does not exist: {root}")
        sys.exit(1)
    
    if not root.is_dir():
        logger.error(f"Root path is not a directory: {root}")
        sys.exit(1)

    api_base = _indexer_api_base(args)
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{api_base}/api/settings/roots",
                json={"path": str(root)},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                try:
                    error = resp.json().get("error", resp.text)
                except Exception:
                    error = resp.text
                logger.error(f"Failed to add root via indexer API: {error}")
                sys.exit(1)
    except Exception as exc:
        logger.error(f"Failed to reach indexer API at {api_base}: {exc}")
        sys.exit(1)

    logger.info(f"Requested add-root via indexer API: {root}")
    print("Command sent to indexer API. Root will be added shortly.")


def cmd_remove_root(args):
    """Remove a document root directory."""
    root = Path(args.root).resolve()

    api_base = _indexer_api_base(args)
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(
                f"{api_base}/api/settings/roots",
                params={"path": str(root)},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                try:
                    error = resp.json().get("error", resp.text)
                except Exception:
                    error = resp.text
                logger.error(f"Failed to remove root via indexer API: {error}")
                sys.exit(1)
    except Exception as exc:
        logger.error(f"Failed to reach indexer API at {api_base}: {exc}")
        sys.exit(1)

    logger.info(f"Requested remove-root via indexer API: {root}")
    print("Command sent to indexer API. Root will be removed shortly.")


def cmd_list_roots(args):
    """List all document root directories."""
    api_base = _indexer_api_base(args)
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{api_base}/api/settings/roots")
            if resp.status_code != 200:
                try:
                    error = resp.json().get("error", resp.text)
                except Exception:
                    error = resp.text
                logger.error(f"Failed to list roots via indexer API: {error}")
                sys.exit(1)
            roots = resp.json()
    except Exception as exc:
        logger.error(f"Failed to reach indexer API at {api_base}: {exc}")
        sys.exit(1)

    print(f"\nDocument roots ({len(roots)}):")
    if roots:
        for root in roots:
            print(f"  - {root.get('path')}")
    else:
        print("  (none)")


def cmd_resync(args):
    """Resync indexer with all files in current roots."""
    api_base = _indexer_api_base(args)
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{api_base}/api/dashboard/reconcile")
            if resp.status_code != 200:
                try:
                    error = resp.json().get("error", resp.text)
                except Exception:
                    error = resp.text
                logger.error(f"Failed to queue resync via indexer API: {error}")
                sys.exit(1)
    except Exception as exc:
        logger.error(f"Failed to reach indexer API at {api_base}: {exc}")
        sys.exit(1)

    logger.info("Queued resync command via indexer API")
    print("Resync command sent. Indexer will sync all files with current roots.")


def cmd_integrity(args):
    """Check integrity of indexed files vs watched files."""
    api_base = _indexer_api_base(args)
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{api_base}/api/dashboard/integrity")
            if resp.status_code != 200:
                try:
                    error = resp.json().get("error", resp.text)
                except Exception:
                    error = resp.text
                logger.error(f"Failed to queue integrity check via indexer API: {error}")
                sys.exit(1)
            report = resp.json()
    except Exception as exc:
        logger.error(f"Failed to reach indexer API at {api_base}: {exc}")
        sys.exit(1)

    if "error" in report:
        logger.error(f"Integrity check failed: {report['error']}")
        sys.exit(1)

    print("=" * 60)
    print("INTEGRITY CHECK REPORT")
    print("=" * 60)

    roots = report.get("roots", [])
    print(f"\nWatched Roots ({len(roots)}):")
    for root in roots:
        print(f"  - {root}")

    stats = report.get("stats", {})
    print(f"\nIndexed Documents:")
    print(f"  Total documents: {stats.get('document_count', 0)}")
    print(f"  Total chunks: {stats.get('chunk_count', 0)}")
    print(f"  Total embeddings: {stats.get('embedding_count', 0)}")

    print(f"\nFiles in Watched Roots:")
    for item in report.get("files_by_root", []):
        print(f"  {item.get('root')}: {item.get('count')} files")
    totals = report.get("totals", {})
    if totals:
        print(f"  Total: {totals.get('actual_files', 0)} files")

    missing = report.get("missing_from_index", {})
    orphaned = report.get("orphaned_in_index", {})
    modified = report.get("modified_files", {})

    print(f"\nIntegrity Status:")
    print(f"  Files in sync: {totals.get('in_sync', 0)}")
    print(f"  Missing from index (need add): {missing.get('count', 0)}")
    print(f"  Orphaned in index (need remove): {orphaned.get('count', 0)}")
    print(f"  Modified (need update): {modified.get('count', 0)}")

    if missing.get("sample"):
        print(f"\nMissing from index:")
        for f in missing.get("sample", []):
            print(f"  + {f}")
        if missing.get("count", 0) > len(missing.get("sample", [])):
            print(f"  ... and {missing.get('count', 0) - len(missing.get('sample', []))} more")

    if orphaned.get("sample"):
        print(f"\nOrphaned in index:")
        for f in orphaned.get("sample", []):
            print(f"  - {f}")
        if orphaned.get("count", 0) > len(orphaned.get("sample", [])):
            print(f"  ... and {orphaned.get('count', 0) - len(orphaned.get('sample', []))} more")

    if modified.get("sample"):
        print(f"\nModified files:")
        for f in modified.get("sample", []):
            print(f"  ~ {f}")
        if modified.get("count", 0) > len(modified.get("sample", [])):
            print(f"  ... and {modified.get('count', 0) - len(modified.get('sample', []))} more")

    issues = report.get("issues", 0)
    if report.get("in_sync"):
        print(f"\n✓ Index is in sync with watched files")
    else:
        print(f"\n⚠ Index has {issues} issue(s). Run 'resync' to fix.")

    print("=" * 60)


def cmd_gateway(args):
    """Start the email gateway service."""
    import asyncio
    from src.gateway.email.config import GatewayConfig
    from src.gateway.email.service import GatewayService

    config = GatewayConfig(
        bot_email=args.bot_email or os.environ.get("BOT_EMAIL", ""),
        bot_username=args.bot_username or os.environ.get("BOT_USERNAME", ""),
        bot_password=args.bot_password or os.environ.get("BOT_PASSWORD", ""),
        ews_server=args.ews_server or os.environ.get("EWS_SERVER"),
        auth_type=args.auth_type,
        authorized_users=[u.strip() for u in args.authorized_users.split(",")] if args.authorized_users else [],
        poll_interval=args.poll_interval,
        send_throttle=args.send_throttle,
        adk_base_url=f"http://{args.adk_host}:{args.adk_port}",
        db_path=str(Path(args.db_dir).resolve() / "gateway.db"),
        default_agent=args.default_agent,
    )

    if not config.bot_email or not config.bot_username or not config.bot_password:
        logger.error("Bot credentials required. Set BOT_EMAIL, BOT_USERNAME, BOT_PASSWORD env vars or use --bot-* flags")
        sys.exit(1)

    shutdown = GracefulShutdown()
    service = GatewayService(config)

    try:
        service.setup()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run():
            task = asyncio.create_task(service.run())
            while not shutdown.should_exit:
                await asyncio.sleep(1)
            task.cancel()

        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        pass
    finally:
        service.shutdown()
        logger.info("Gateway stopped")


def cmd_api_server(args):
    """Start the ADK API server."""
    # Load agent model from settings DB before importing agent modules
    db_dir = Path(args.db_dir).resolve()
    os.environ["SOSIE_AUTH_DB_PATH"] = str((db_dir / "auth.db").resolve())
    watcher_db = db_dir / "watcher.db"
    if watcher_db.exists():
        from src.indexer.settings import SettingsManager
        sm = SettingsManager(watcher_db)
        agent_cfg = sm.get_agent_config_overrides()
        os.environ["SOSIE_AGENT_MODEL"] = agent_cfg["model_id"]
        logger.info(f"Agent model: {agent_cfg['model_id']}")

    from src.agent_server import start_server
    
    start_server(
        host=args.host,
        port=args.port,
        session_db=args.session_db,
        agents_dir=args.agents_dir,
    )


def cmd_research(args):
    """Deep research with the research agent via API server (SSE streaming)."""
    import httpx
    import json
    import uuid
    import logging
    
    # Suppress httpx logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    api_base = f"http://{args.host}:{args.port}"
    user_id = args.user
    session_id = args.session or str(uuid.uuid4())
    agent_name = "deep_research_agent"
    depth = args.depth
    
    print(f"Connecting to {api_base}")
    print(f"Agent: {agent_name}")
    print(f"Research Depth: {depth}")
    print(f"User: {user_id}")
    
    # Create session on the server first
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{api_base}/apps/{agent_name}/users/{user_id}/sessions",
                json={},
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code != 200:
                print(f"Error creating session: {resp.status_code}")
                print(f"Response: {resp.text}")
                return
            session_data = resp.json()
            session_id = session_data.get("id", session_id)
    except httpx.ConnectError:
        print(f"Error: Cannot connect to API server at {api_base}")
        print("Start the server with: python -m src.cli api-server")
        return
    
    print(f"Session: {session_id}")
    print("Type 'exit' or 'quit' to end. Enter your research query:\n")
    
    while True:
        try:
            user_input = input("Research Query: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ('exit', 'quit'):
                print("Goodbye!")
                break
            
            # Prepend depth instruction
            research_query = f"[DEPTH: {depth.upper()}]\n\n{user_input}"
            
            # SSE streaming request to ADK API server
            try:
                print("\n--- Researching... ---\n")
                tool_calls = []
                
                with httpx.Client(timeout=300.0) as client:
                    with client.stream(
                        "POST",
                        f"{api_base}/run_sse",
                        json={
                            "appName": agent_name,
                            "userId": user_id,
                            "sessionId": session_id,
                            "newMessage": {
                                "role": "user",
                                "parts": [{"text": research_query}]
                            },
                            "streaming": True
                        },
                        headers={"Content-Type": "application/json"}
                    ) as response:
                        if response.status_code != 200:
                            print(f"\nError: Server returned {response.status_code}")
                            try:
                                error_body = response.read().decode()
                                print(f"Response: {error_body}")
                            except:
                                pass
                            continue
                        
                        last_text = ""
                        
                        for line in response.iter_lines():
                            if not line:
                                continue
                            if line.startswith("data: "):
                                try:
                                    data = json.loads(line[6:])
                                    # Extract content from agent response
                                    if "content" in data:
                                        content = data["content"]
                                        if isinstance(content, dict) and "parts" in content:
                                            for part in content["parts"]:
                                                if isinstance(part, dict):
                                                    # Show tool calls
                                                    if "functionCall" in part:
                                                        fc = part["functionCall"]
                                                        tool_name = fc.get("name", "unknown")
                                                        tool_args = fc.get("args", {})
                                                        tool_calls.append(tool_name)
                                                        print(f"  🔧 {tool_name}", end="")
                                                        if tool_args.get("query"):
                                                            print(f': "{tool_args["query"][:50]}..."', end="")
                                                        print(flush=True)
                                                    # Show text output (handle cumulative content)
                                                    if "text" in part:
                                                        text = part["text"]
                                                        if text.startswith(last_text):
                                                            print(text[len(last_text):], end="", flush=True)
                                                            last_text = text
                                                        elif not last_text:
                                                            print(text, end="", flush=True)
                                                            last_text = text
                                except json.JSONDecodeError:
                                    pass
                        
                        print(f"\n\n--- Research complete ({len(tool_calls)} tool calls) ---\n")
                        
            except httpx.ConnectError:
                print(f"\nError: Cannot connect to API server at {api_base}")
                print("Start the server with: python -m src.cli api-server")
                break
            except httpx.ReadTimeout:
                print("\nError: Request timed out. Deep research may take a while.")
                continue
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break


def _send_chat_message(api_base: str, agent_name: str, user_id: str, session_id: str, message: str) -> str:
    """Send a single chat message and return the response."""
    import httpx
    import json
    
    response_text = ""
    last_text = ""
    
    with httpx.Client(timeout=120.0) as client:
        with client.stream(
            "POST",
            f"{api_base}/run_sse",
            json={
                "appName": agent_name,
                "userId": user_id,
                "sessionId": session_id,
                "newMessage": {
                    "role": "user",
                    "parts": [{"text": message}]
                },
                "streaming": True
            },
            headers={"Content-Type": "application/json"}
        ) as response:
            if response.status_code != 200:
                return f"Error: Server returned {response.status_code}"
            
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if "content" in data:
                            content = data["content"]
                            if isinstance(content, dict) and "parts" in content:
                                for part in content["parts"]:
                                    if isinstance(part, dict) and "text" in part:
                                        text = part["text"]
                                        if text.startswith(last_text):
                                            last_text = text
                                        elif not last_text:
                                            last_text = text
                    except json.JSONDecodeError:
                        pass
    
    return last_text


def cmd_chat(args):
    """Chat with the Q&A agent via API server (SSE streaming)."""
    import httpx
    import json
    import uuid
    import logging
    
    # Suppress httpx logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    api_base = f"http://{args.host}:{args.port}"
    user_id = args.user
    session_id = args.session or str(uuid.uuid4())
    agent_name = args.agent
    single_turn = args.message is not None
    
    if not single_turn:
        print(f"Connecting to {api_base}")
        print(f"Agent: {agent_name}")
        print(f"User: {user_id}")
    
    # Create session on the server first
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{api_base}/apps/{agent_name}/users/{user_id}/sessions",
                json={},
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code != 200:
                if single_turn:
                    print(f"Error creating session: {resp.status_code}", file=sys.stderr)
                else:
                    print(f"Error creating session: {resp.status_code}")
                    print(f"Response: {resp.text}")
                return
            session_data = resp.json()
            session_id = session_data.get("id", session_id)
    except httpx.ConnectError:
        if single_turn:
            print(f"Error: Cannot connect to API server at {api_base}", file=sys.stderr)
        else:
            print(f"Error: Cannot connect to API server at {api_base}")
            print("Start the server with: python -m src.cli api-server")
        return
    
    # Single-turn mode: send message and print response
    if single_turn:
        try:
            response = _send_chat_message(api_base, agent_name, user_id, session_id, args.message)
            print(response)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
        return
    
    print(f"Session: {session_id}")
    print("Type 'exit' or 'quit' to end the conversation.\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ('exit', 'quit'):
                print("Goodbye!")
                break
            
            # SSE streaming request to ADK API server
            try:
                with httpx.Client(timeout=120.0) as client:
                    with client.stream(
                        "POST",
                        f"{api_base}/run_sse",
                        json={
                            "appName": agent_name,
                            "userId": user_id,
                            "sessionId": session_id,
                            "newMessage": {
                                "role": "user",
                                "parts": [{"text": user_input}]
                            },
                            "streaming": True
                        },
                        headers={"Content-Type": "application/json"}
                    ) as response:
                        if response.status_code != 200:
                            print(f"\nError: Server returned {response.status_code}")
                            try:
                                error_body = response.read().decode()
                                print(f"Response: {error_body}")
                            except:
                                pass
                            continue
                        
                        print("\nAgent: ", end="", flush=True)
                        
                        last_text = ""
                        
                        for line in response.iter_lines():
                            if not line:
                                continue
                            if line.startswith("data: "):
                                try:
                                    data = json.loads(line[6:])
                                    # Extract text from agent response
                                    if "content" in data:
                                        content = data["content"]
                                        if isinstance(content, dict) and "parts" in content:
                                            for part in content["parts"]:
                                                if isinstance(part, dict) and "text" in part:
                                                    text = part["text"]
                                                    # ADK sends cumulative content
                                                    # Only print the new portion
                                                    if text.startswith(last_text):
                                                        # Cumulative: print delta
                                                        print(text[len(last_text):], end="", flush=True)
                                                        last_text = text
                                                    elif last_text and text != last_text:
                                                        # Different text, might be a new response
                                                        # Skip if it looks like a repeat
                                                        pass
                                                    else:
                                                        # First text or exact match
                                                        if not last_text:
                                                            print(text, end="", flush=True)
                                                            last_text = text
                                except json.JSONDecodeError:
                                    pass
                        
                        print("\n")
                        
            except httpx.ConnectError:
                print(f"\nError: Cannot connect to API server at {api_base}")
                print("Start the server with: python -m src.cli api-server")
                break
            except httpx.ReadTimeout:
                print("\nError: Request timed out. The server may be overloaded.")
                continue
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break


def main():
    parser = argparse.ArgumentParser(
        description="CLI for watcher and indexer processes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start watcher only
  python -m src.cli watcher --roots ./documents --db watcher.db

  # Start indexer only (requires watcher DB)
  python -m src.cli indexer --watcher-db watcher.db --vector-db vectors.db

  # Start both watcher and indexer
  python -m src.cli all --roots ./documents --db-dir ./data

  # Search indexed documents
  python -m src.cli search --vector-db vectors.db "how does authentication work"

  # Show statistics
  python -m src.cli stats --vector-db vectors.db
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Watcher command
    watcher_parser = subparsers.add_parser("watcher", help="Run file watcher")
    watcher_parser.add_argument("--roots", nargs="+", required=True, help="Root directories to watch")
    watcher_parser.add_argument("--db", default="watcher.db", help="Watcher database path")
    watcher_parser.add_argument("--debounce", type=int, default=50, help="Debounce time in ms")
    watcher_parser.add_argument("--batch-timeout", type=int, default=200, help="Batch timeout in ms")
    watcher_parser.add_argument("--move-correlation", type=int, default=100, help="Move correlation window in ms")
    watcher_parser.set_defaults(func=cmd_watcher)
    
    # Indexer command (watcher + indexer together)
    indexer_parser = subparsers.add_parser("indexer", help="Run file watcher and document indexer")
    indexer_parser.add_argument("--roots", nargs="+", default=[], help="Root directories to watch (can be added later via API)")
    indexer_parser.add_argument("--db-dir", default="./data", help="Database directory")
    indexer_parser.add_argument("--api-key", help="OpenAI API key (or set OPENAI_API_KEY)")
    indexer_parser.add_argument("--proxy", help="HTTPS proxy URL")
    indexer_parser.add_argument("--embedding-model", default="text-embedding-v4", help="Embedding model")
    indexer_parser.add_argument("--chunk-size", type=int, default=1000, help="Chunk size")
    indexer_parser.add_argument("--chunk-overlap", type=int, default=200, help="Chunk overlap")
    indexer_parser.add_argument("--debounce", type=int, default=50, help="Debounce time in ms")
    indexer_parser.set_defaults(func=cmd_all)
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search indexed documents")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--vector-db", required=True, help="Vector database path")
    search_parser.add_argument("--top-k", type=int, default=5, help="Number of results")
    search_parser.add_argument("--api-key", help="OpenAI API key (or set OPENAI_API_KEY)")
    search_parser.add_argument("--proxy", help="HTTPS proxy URL")
    search_parser.set_defaults(func=cmd_search)
    
    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show indexer statistics")
    stats_parser.add_argument("--vector-db", required=True, help="Vector database path")
    stats_parser.set_defaults(func=cmd_stats)
    
    # Add root command
    add_root_parser = subparsers.add_parser("add-root", help="Add a document root directory")
    add_root_parser.add_argument("root", help="Root directory to add")
    add_root_parser.add_argument("--api-host", default="localhost", help="Indexer API host (default: localhost)")
    add_root_parser.add_argument("--api-port", type=int, default=8001, help="Indexer API port (default: 8001)")
    add_root_parser.set_defaults(func=cmd_add_root)
    
    # Remove root command
    remove_root_parser = subparsers.add_parser("remove-root", help="Remove a document root directory")
    remove_root_parser.add_argument("root", help="Root directory to remove")
    remove_root_parser.add_argument("--api-host", default="localhost", help="Indexer API host (default: localhost)")
    remove_root_parser.add_argument("--api-port", type=int, default=8001, help="Indexer API port (default: 8001)")
    remove_root_parser.set_defaults(func=cmd_remove_root)
    
    # List roots command
    list_roots_parser = subparsers.add_parser("list-roots", help="List document root directories")
    list_roots_parser.add_argument("--api-host", default="localhost", help="Indexer API host (default: localhost)")
    list_roots_parser.add_argument("--api-port", type=int, default=8001, help="Indexer API port (default: 8001)")
    list_roots_parser.set_defaults(func=cmd_list_roots)
    
    # Resync command
    resync_parser = subparsers.add_parser("resync", help="Resync indexer with all files in current roots")
    resync_parser.add_argument("--api-host", default="localhost", help="Indexer API host (default: localhost)")
    resync_parser.add_argument("--api-port", type=int, default=8001, help="Indexer API port (default: 8001)")
    resync_parser.set_defaults(func=cmd_resync)
    
    # Integrity check command
    integrity_parser = subparsers.add_parser("integrity", help="Check integrity of indexed files vs watched files")
    integrity_parser.add_argument("--api-host", default="localhost", help="Indexer API host (default: localhost)")
    integrity_parser.add_argument("--api-port", type=int, default=8001, help="Indexer API port (default: 8001)")
    integrity_parser.set_defaults(func=cmd_integrity)
    
    # Gateway command
    gateway_parser = subparsers.add_parser("gateway", help="Start the email gateway service")
    gateway_parser.add_argument("--bot-email", default=None, help="Bot email address (or BOT_EMAIL env)")
    gateway_parser.add_argument("--bot-username", default=None, help="Bot username (or BOT_USERNAME env)")
    gateway_parser.add_argument("--bot-password", default=None, help="Bot password (or BOT_PASSWORD env)")
    gateway_parser.add_argument("--ews-server", default=None, help="Exchange server hostname (or EWS_SERVER env)")
    gateway_parser.add_argument("--auth-type", default="NTLM", choices=["NTLM", "basic"], help="EWS auth type")
    gateway_parser.add_argument("--authorized-users", default=None, help="Comma-separated authorized email addresses")
    gateway_parser.add_argument("--poll-interval", type=float, default=10.0, help="Inbox poll interval in seconds")
    gateway_parser.add_argument("--send-throttle", type=float, default=1.0, help="Delay between outbound emails")
    gateway_parser.add_argument("--adk-host", default="localhost", help="ADK API server host")
    gateway_parser.add_argument("--adk-port", type=int, default=8000, help="ADK API server port")
    gateway_parser.add_argument("--db-dir", default="./data", help="Database directory")
    gateway_parser.add_argument("--default-agent", default="ask_hti_agent", help="Default agent for untagged emails")
    gateway_parser.set_defaults(func=cmd_gateway)

    # API server command
    api_server_parser = subparsers.add_parser("api-server", help="Start the ADK API server")
    api_server_parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    api_server_parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    api_server_parser.add_argument("--db-dir", default="./data", help="Database directory (default: ./data)")
    api_server_parser.add_argument("--session-db", default=None, help="Session database path (default: platform app data dir)")
    api_server_parser.add_argument("--agents-dir", default=None, help="Agents directory (default: src/agents)")
    api_server_parser.set_defaults(func=cmd_api_server)
    
    # Chat command
    chat_parser = subparsers.add_parser("chat", help="Chat with an agent via API server")
    chat_parser.add_argument("--host", default="localhost", help="API server host (default: localhost)")
    chat_parser.add_argument("--port", type=int, default=8000, help="API server port (default: 8000)")
    chat_parser.add_argument("--agent", default="doc_qa_agent", help="Agent name (default: doc_qa_agent)")
    chat_parser.add_argument("--user", default="default_user", help="User ID (default: default_user)")
    chat_parser.add_argument("--session", default=None, help="Session ID (auto-generated if not provided)")
    chat_parser.add_argument("-m", "--message", default=None, help="Single message to send (returns response and exits)")
    chat_parser.set_defaults(func=cmd_chat)
    
    # Research command
    research_parser = subparsers.add_parser("research", help="Deep research with the research agent")
    research_parser.add_argument("--host", default="localhost", help="API server host (default: localhost)")
    research_parser.add_argument("--port", type=int, default=8000, help="API server port (default: 8000)")
    research_parser.add_argument("--depth", default="standard", choices=["quick", "standard", "deep"],
                                  help="Research depth: quick (1-2 searches), standard (3-5), deep (6+)")
    research_parser.add_argument("--user", default="default_user", help="User ID (default: default_user)")
    research_parser.add_argument("--session", default=None, help="Session ID (auto-generated if not provided)")
    research_parser.set_defaults(func=cmd_research)
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    args.func(args)


if __name__ == "__main__":
    main()
