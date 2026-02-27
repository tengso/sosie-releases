"""Indexer REST API server — FastAPI edition."""

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import httpx
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, Response, FileResponse

try:
    from src.watcher import WatcherProcess, WatcherConfig
except ImportError:  # pragma: no cover - fallback for editable installs
    try:
        from watcher import WatcherProcess, WatcherConfig
    except ImportError:  # pragma: no cover
        WatcherProcess = None
        WatcherConfig = None

from .auth import AuthManager
from .exceptions import RootOverlapError
from .models import generate_document_id

if TYPE_CHECKING:
    from .process import IndexerProcess

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IndexerAPIConfig:
    vector_db: Path
    watcher_db: Path
    web_dist_path: Optional[Path] = None  # Path to React frontend build
    agent_api_url: str = "http://localhost:8000"  # ADK agent server URL
    remote_mode: bool = False  # Enable file upload mode
    uploads_dir: Optional[Path] = None  # Managed uploads directory
    auth_db_path: Optional[Path] = None  # Auth database (defaults to watcher_db dir)


# ---------------------------------------------------------------------------
# Helpers (unchanged from original)
# ---------------------------------------------------------------------------

def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _to_unix_seconds(dt_str: Optional[str]) -> int:
    if not dt_str:
        return 0
    try:
        from datetime import datetime

        if "T" not in dt_str and " " in dt_str:
            dt_str = dt_str.replace(" ", "T")
        return int(datetime.fromisoformat(dt_str).timestamp())
    except Exception:
        return 0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _basename(path: str) -> str:
    try:
        return Path(path).name
    except Exception:
        return path


def _file_size(path: str) -> int:
    try:
        return int(Path(path).stat().st_size)
    except Exception:
        return 0


def _doc_status(path: str) -> str:
    return "indexed" if Path(path).exists() else "missing"


def _match_root(file_path: str, roots: List[str]) -> str:
    best = ""
    for root in roots:
        normalized = root.rstrip("/")
        if file_path.startswith(normalized + os.sep) or file_path.startswith(normalized + "/") or file_path.startswith(root):
            if len(root) > len(best):
                best = root
    return best


def _get_disabled_roots(indexer: Optional["IndexerProcess"]) -> Optional[List[str]]:
    if indexer is None:
        return None
    paths = indexer.get_disabled_root_paths()
    return paths or None


SHARED_DOCS_FOLDER = "shared_documents"


def _get_user_search_filters(
    user,
    auth_mgr: AuthManager,
    cfg: "IndexerAPIConfig",
    disabled: Optional[List[str]] = None,
    agent_name: Optional[str] = None,
) -> Tuple[Optional[List[str]], Optional[str], Optional[List[str]]]:
    """Build search filters: exclude list + include-based upload scoping.

    Returns:
        (exclude_root_paths, include_under, include_roots)
        - exclude_root_paths: disabled roots + per-agent knowledge filter
        - include_under: uploads dir (scope boundary); None in local mode
        - include_roots: allowed sub-dirs within uploads (user's own + shared)
    """
    excludes = list(disabled or [])
    include_under: Optional[str] = None
    include_roots: Optional[List[str]] = None

    # Include-based upload scoping (remote mode only)
    if cfg.remote_mode and cfg.uploads_dir:
        include_under = str(cfg.uploads_dir.resolve())
        include_roots = [
            str((cfg.uploads_dir / user.username).resolve()),
            str((cfg.uploads_dir / SHARED_DOCS_FOLDER).resolve()),
        ]

    # Per-agent knowledge root filter
    # user.knowledge_roots is Dict[agent_name, List[str] | null] or None
    if user.knowledge_roots and agent_name:
        selected = user.knowledge_roots.get(agent_name)  # None = all roots
        if selected is not None:
            try:
                conn = sqlite3.connect(str(cfg.watcher_db))
                rows = conn.execute("SELECT path FROM roots WHERE enabled = 1").fetchall()
                conn.close()
                all_enabled = {r[0] for r in rows}
                selected_set = set(selected)
                for root_path in all_enabled:
                    if root_path not in selected_set:
                        excludes.append(root_path)
            except Exception:
                pass
    return excludes or None, include_under, include_roots


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(cfg: IndexerAPIConfig, indexer: Optional["IndexerProcess"] = None) -> FastAPI:
    app = FastAPI(title="Sosie Indexer API", docs_url=None, redoc_url=None)

    # Store references on app state
    app.state.cfg = cfg
    app.state.indexer = indexer

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # ------------------------------------------------------------------
    # Auth setup
    # ------------------------------------------------------------------

    auth_db = cfg.auth_db_path or (cfg.watcher_db.parent / "auth.db")
    auth_mgr = AuthManager(auth_db)
    app.state.auth_mgr = auth_mgr

    # In local mode, ensure default user exists
    if not cfg.remote_mode:
        local_user = auth_mgr.ensure_local_user()
        app.state.local_user = local_user

    # Routes exempt from auth (prefix match)
    _AUTH_EXEMPT = {
        "/api/auth/login",
        "/api/auth/register",
        "/api/settings/mode",
        "/api/dashboard/health",
    }

    # Internal service token for agent→indexer server-to-server calls
    _service_token = os.environ.get("SOSIE_SERVICE_TOKEN")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path

        # Static files, docs, and SPA routes don't need auth
        if not path.startswith("/api/"):
            response = await call_next(request)
            return response

        # Exempt routes
        if path in _AUTH_EXEMPT:
            response = await call_next(request)
            return response

        # Internal service token bypass (agent tools → indexer)
        if _service_token:
            auth_header = request.headers.get("X-Service-Token")
            if auth_header == _service_token:
                # Resolve actual user from X-User-Id header if provided
                user_id_header = request.headers.get("X-User-Id")
                if user_id_header:
                    resolved = auth_mgr.get_user_by_username(user_id_header)
                    if resolved:
                        request.state.user = resolved
                    else:
                        request.state.user = auth_mgr.get_internal_service_user()
                else:
                    request.state.user = auth_mgr.get_internal_service_user()
                response = await call_next(request)
                return response

        if cfg.remote_mode:
            # Remote mode: validate session cookie
            token = request.cookies.get("sosie_session")
            if not token:
                return JSONResponse({"error": "Authentication required"}, status_code=401)
            user = auth_mgr.validate_token(token)
            if not user:
                return JSONResponse({"error": "Invalid or expired session"}, status_code=401)
            request.state.user = user
        else:
            # Local mode: re-read from DB to pick up field changes
            request.state.user = auth_mgr.get_user_by_id(app.state.local_user.id) or app.state.local_user

        response = await call_next(request)
        return response

    # ------------------------------------------------------------------
    # Auth endpoints
    # ------------------------------------------------------------------

    @app.post("/api/auth/register")
    async def auth_register(request: Request):
        if not cfg.remote_mode:
            return JSONResponse({"error": "Registration is not available in local mode"}, status_code=403)
        payload = await request.json()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        display_name = str(payload.get("display_name", "")).strip() or None
        raw_email = payload.get("email")
        email = None if raw_email is None else (str(raw_email).strip() or None)
        try:
            user = auth_mgr.create_user(username, password, display_name, email=email)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        # Auto-login after registration
        token = auth_mgr.create_session_token(user.id)
        response = JSONResponse(user.to_dict())
        response.set_cookie(
            "sosie_session", token,
            httponly=True, samesite="lax", max_age=30 * 86400,
        )
        return response

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        payload = await request.json()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        user = auth_mgr.verify_login(username, password)
        if not user:
            return JSONResponse({"error": "Invalid username or password"}, status_code=401)
        token = auth_mgr.create_session_token(user.id)
        response = JSONResponse(user.to_dict())
        response.set_cookie(
            "sosie_session", token,
            httponly=True, samesite="lax", max_age=30 * 86400,
        )
        return response

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        token = request.cookies.get("sosie_session")
        if token:
            auth_mgr.delete_token(token)
        response = JSONResponse({"success": True})
        response.delete_cookie("sosie_session")
        return response

    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        user = request.state.user
        return user.to_dict()

    @app.patch("/api/auth/me")
    async def auth_update_me(request: Request):
        user = request.state.user
        payload = await request.json()
        updates = {}
        if "display_name" in payload:
            updates["display_name"] = str(payload["display_name"]).strip()
        if "avatar_url" in payload:
            updates["avatar_url"] = payload["avatar_url"]
        if "email" in payload:
            raw_email = payload["email"]
            updates["email"] = None if raw_email is None else (str(raw_email).strip() or None)
        if "picked_agents" in payload:
            updates["picked_agents"] = payload["picked_agents"]
        if "agent_overrides" in payload:
            updates["agent_overrides"] = payload["agent_overrides"]
        try:
            updated = auth_mgr.update_user(user.id, **updates)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not updated:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return updated.to_dict()

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @app.get("/api/dashboard/stats")
    def dashboard_stats():
        documents = chunks = embeddings = storage_bytes = 0
        try:
            with _connect(cfg.vector_db) as vdb:
                documents = vdb.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
                chunks = vdb.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
                embeddings = vdb.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()["c"]
                paths = [r["file_path"] for r in vdb.execute("SELECT file_path FROM documents")]
                storage_bytes = sum(_file_size(p) for p in paths)
        except sqlite3.Error:
            pass
        return {
            "documents": int(documents),
            "chunks": int(chunks),
            "embeddings": int(embeddings),
            "pending_jobs": 0, "running_jobs": 0, "failed_jobs": 0, "completed_jobs": 0,
            "storage_bytes": int(storage_bytes),
        }

    @app.get("/api/dashboard/health")
    def dashboard_health():
        try:
            with _connect(cfg.vector_db) as vdb:
                vector_count = vdb.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()["c"]
        except Exception:
            vector_count = 0
        db_size_bytes = _file_size(str(cfg.vector_db))
        watcher_running = False
        try:
            with _connect(cfg.watcher_db) as wdb:
                row = wdb.execute("SELECT value FROM watcher_status WHERE key = 'running'").fetchone()
                if row and str(row["value"]).lower() in {"1", "true", "yes"}:
                    watcher_running = True
        except Exception:
            pass
        return {
            "database_ok": True, "vector_index_ok": True,
            "vector_count": int(vector_count),
            "db_size_bytes": int(db_size_bytes),
            "watcher_running": watcher_running,
        }

    @app.get("/api/dashboard/activity")
    def dashboard_activity(limit: int = 50):
        items: List[Dict[str, Any]] = []
        try:
            with _connect(cfg.watcher_db) as wdb:
                try:
                    rows = wdb.execute(
                        "SELECT type, message, path, created_at FROM activity_log ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    for row in rows:
                        items.append({
                            "type": row["type"],
                            "message": row["message"],
                            "timestamp": int(float(row["created_at"])) if row["created_at"] else 0,
                            "doc_id": None,
                            "filename": _basename(row["path"]) if row["path"] else None,
                        })
                except Exception:
                    rows = wdb.execute(
                        "SELECT payload, created_at FROM events ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    for row in rows:
                        try:
                            payload = json.loads(row["payload"])
                        except Exception:
                            payload = {"message": str(row["payload"])}
                        msg = payload.get("message") or payload.get("event") or payload.get("type") or "event"
                        doc_id = payload.get("doc_id") or payload.get("file_path")
                        filename = _basename(str(payload.get("filename") or payload.get("file_path") or "")) or None
                        items.append({
                            "type": payload.get("type") or "activity",
                            "message": str(msg),
                            "timestamp": int(float(row["created_at"])) if row["created_at"] is not None else 0,
                            "doc_id": str(doc_id) if doc_id else None,
                            "filename": filename,
                        })
        except Exception:
            pass
        return items

    @app.get("/api/dashboard/index-overview")
    def dashboard_index_overview():
        roots: List[Dict[str, Any]] = []
        recent_documents: List[Dict[str, Any]] = []
        with _connect(cfg.watcher_db) as wdb:
            root_rows = wdb.execute("SELECT path, added_at FROM roots ORDER BY added_at DESC").fetchall()
        with _connect(cfg.vector_db) as vdb:
            total_documents = vdb.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
            total_chunks = vdb.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
            total_vectors = vdb.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()["c"]
            recent_rows = vdb.execute(
                "SELECT file_path, updated_at FROM documents ORDER BY updated_at DESC LIMIT 10"
            ).fetchall()
            for recent in recent_rows:
                fp = recent["file_path"]
                chunk_count = vdb.execute("SELECT COUNT(*) AS c FROM chunks WHERE file_path = ?", (fp,)).fetchone()["c"]
                recent_documents.append({
                    "doc_id": fp,
                    "document_id": generate_document_id(Path(fp)),
                    "filename": _basename(fp), "path": fp,
                    "status": _doc_status(fp),
                    "updated_at": _to_unix_seconds(recent["updated_at"]),
                    "root_path": _match_root(fp, [r["path"] for r in root_rows]),
                    "chunk_count": int(chunk_count),
                })
        for row in root_rows:
            rp = row["path"]
            with _connect(cfg.vector_db) as vdb:
                doc_count = vdb.execute("SELECT COUNT(*) AS c FROM documents WHERE file_path LIKE ?", (rp.rstrip("/") + "%",)).fetchone()["c"]
                chunk_count = vdb.execute("SELECT COUNT(*) AS c FROM chunks WHERE file_path LIKE ?", (rp.rstrip("/") + "%",)).fetchone()["c"]
            roots.append({
                "root_id": abs(hash(rp)) % (2**31), "path": rp,
                "doc_count": int(doc_count), "chunk_count": int(chunk_count),
                "created_at": row["added_at"],
            })
        return {
            "roots": roots, "total_documents": int(total_documents),
            "total_chunks": int(total_chunks), "total_vectors": int(total_vectors),
            "recent_documents": recent_documents,
        }

    @app.get("/api/dashboard/jobs")
    def dashboard_jobs():
        return []

    def _dashboard_resync():
        error = _queue_system_command(indexer, cfg, "resync")
        if error:
            return JSONResponse({"error": error}, status_code=400)
        return {"success": True, "message": "Resync queued"}
    app.post("/api/dashboard/reconcile")(_dashboard_resync)
    app.post("/api/dashboard/resync")(_dashboard_resync)

    def _dashboard_integrity():
        if indexer:
            report = indexer.build_integrity_report()
        else:
            report = {"error": "Indexer is not running"}
        if "error" in report:
            return JSONResponse(report, status_code=400)
        return report
    app.post("/api/dashboard/integrity")(_dashboard_integrity)
    app.post("/api/dashboard/integrity-check")(_dashboard_integrity)

    @app.post("/api/dashboard/retry-errors")
    def dashboard_retry_errors():
        return {"success": True, "retried": 0}

    @app.post("/api/dashboard/sync-vectors")
    def dashboard_sync_vectors():
        return {"success": True, "message": "Sync queued"}

    @app.post("/api/dashboard/rebuild-embeddings")
    def dashboard_rebuild_embeddings():
        return {"success": True, "message": "Rebuild queued"}

    @app.post("/api/dashboard/reinitialize")
    def dashboard_reinitialize():
        return {"success": True, "message": "Reinitialize queued"}

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @app.get("/api/settings/mode")
    def settings_mode():
        return {
            "mode": "remote" if cfg.remote_mode else "local",
            "uploads_dir": str(cfg.uploads_dir) if cfg.uploads_dir else None,
        }

    @app.get("/api/settings/roots")
    def settings_get_roots():
        with _connect(cfg.watcher_db) as wdb:
            rows = wdb.execute("SELECT path, enabled FROM roots ORDER BY added_at DESC").fetchall()
        include_exts = [".pdf", ".docx", ".doc"]
        if indexer:
            include_exts = list(indexer.config.supported_extensions)
        return [
            {
                "path": row["path"],
                "include_exts": include_exts,
                "exclude_dirs": [".git", "node_modules"],
                "enabled": bool(row["enabled"]) if row["enabled"] is not None else True,
            }
            for row in rows
        ]

    @app.get("/api/settings/storage")
    def settings_storage():
        def get_size(p: Path) -> int:
            try:
                return p.stat().st_size if p.exists() else 0
            except Exception:
                return 0
        return {
            "watcher_db": str(cfg.watcher_db), "watcher_db_size": get_size(cfg.watcher_db),
            "vector_db": str(cfg.vector_db), "vector_db_size": get_size(cfg.vector_db),
            "data_dir": str(cfg.watcher_db.parent),
        }

    @app.get("/api/settings/roots/status")
    def settings_roots_status():
        roots_status: List[Dict[str, Any]] = []
        supported_exts = {".pdf", ".txt", ".md", ".rst", ".py", ".js", ".ts", ".docx", ".doc"}
        if indexer:
            supported_exts = set(indexer.config.supported_extensions)
        try:
            with _connect(cfg.watcher_db) as wdb:
                root_rows = wdb.execute("SELECT path, added_at, enabled FROM roots ORDER BY added_at DESC").fetchall()
            with _connect(cfg.vector_db) as vdb:
                for root_row in root_rows:
                    root_path = root_row["path"]
                    root_normalized = root_path.rstrip("/")
                    indexed_count = vdb.execute("SELECT COUNT(*) AS c FROM documents WHERE file_path LIKE ?", (root_normalized + "%",)).fetchone()["c"]
                    actual_count = 0
                    root_dir = Path(root_path)
                    if root_dir.exists():
                        try:
                            for f in root_dir.rglob("*"):
                                if f.is_file() and f.suffix.lower() in supported_exts:
                                    actual_count += 1
                        except Exception:
                            pass
                    pending = max(0, actual_count - indexed_count)
                    if actual_count == 0:
                        status = "scanning"
                    elif pending > 0:
                        status = "indexing"
                    else:
                        status = "ready"
                    roots_status.append({
                        "path": root_path, "status": status,
                        "indexed_count": int(indexed_count), "pending_count": pending,
                        "processing_count": 1 if pending > 0 else 0,
                        "added_at": root_row["added_at"],
                        "enabled": bool(root_row["enabled"]) if "enabled" in root_row.keys() else True,
                    })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return roots_status

    @app.get("/api/settings/models")
    def settings_get_models():
        from .settings import SettingsManager
        sm = SettingsManager(cfg.watcher_db)
        info = sm.get_models_info()
        if indexer is not None:
            stats = indexer._store.get_stats()
            info["has_indexed_docs"] = stats.get("document_count", 0) > 0
        else:
            info["has_indexed_docs"] = False
        return info

    @app.post("/api/settings/roots")
    async def settings_add_root(request: Request):
        payload = await request.json()
        root_path = str(payload.get("path") or "").strip()
        if not root_path:
            return JSONResponse({"error": "Missing path"}, status_code=400)
        normalized = Path(root_path).expanduser().resolve()
        if not normalized.exists():
            return JSONResponse({"error": "Root path does not exist"}, status_code=400)
        if not normalized.is_dir():
            return JSONResponse({"error": "Root path is not a directory"}, status_code=400)
        error = _queue_root_command(indexer, cfg, normalized, "add")
        if error:
            return JSONResponse({"error": error}, status_code=500)
        return {"success": True, "message": "Root added"}

    @app.patch("/api/settings/roots")
    async def settings_toggle_root(request: Request):
        payload = await request.json()
        root_path = str(payload.get("path") or "").strip()
        enabled = payload.get("enabled")
        if not root_path or enabled is None:
            return JSONResponse({"error": "Missing path or enabled"}, status_code=400)
        if indexer is None:
            return JSONResponse({"error": "Indexer not available"}, status_code=503)
        normalized = Path(root_path).expanduser().resolve()
        updated = indexer.set_root_enabled(normalized, bool(enabled))
        if not updated:
            return JSONResponse({"error": "Root not found"}, status_code=404)
        return {"success": True, "enabled": bool(enabled)}

    @app.delete("/api/settings/roots")
    def settings_remove_root(path: str = ""):
        root_path = path.strip()
        if not root_path:
            return JSONResponse({"error": "Missing path"}, status_code=400)
        normalized = Path(root_path).expanduser().resolve()
        error = _queue_root_command(indexer, cfg, normalized, "remove")
        if error:
            return JSONResponse({"error": error}, status_code=500)
        return {"success": True, "message": "Root removed"}

    @app.patch("/api/settings/models")
    async def settings_update_models(request: Request):
        from .settings import SettingsManager, EMBEDDING_PRESETS

        payload = await request.json()
        sm = SettingsManager(cfg.watcher_db)
        agent_model = payload.get("agent_model")
        embedding_model = payload.get("embedding_model")
        reindexing = False

        if agent_model and agent_model != sm.get_agent_model():
            sm.set_agent_model(agent_model)
            os.environ["SOSIE_AGENT_MODEL"] = agent_model
            logger.info("Agent model updated to %s", agent_model)

        if embedding_model and embedding_model != sm.get_embedding_model():
            preset = EMBEDDING_PRESETS.get(embedding_model)
            if not preset:
                return JSONResponse({"error": f"Unknown embedding model: {embedding_model}"}, status_code=400)
            sm.set_embedding_model(embedding_model)
            logger.info("Embedding model updated to %s", embedding_model)
            if indexer is not None:
                overrides = sm.get_embedding_config_overrides()
                indexer.config.embedding.model_id = overrides["model_id"]
                indexer.config.embedding.dimensions = overrides["dimensions"]
                indexer.config.embedding.api_base = overrides["api_base"]
                indexer.config.embedding.api_key_env = overrides["api_key_env"]
                indexer.config.embedding.batch_size = overrides["batch_size"]
                indexer.config.embedding.api_key = None
                indexer._embedder = None
                stats = indexer._store.get_stats()
                if stats.get("document_count", 0) > 0:
                    try:
                        indexer._store.clear()
                        logger.info("Vector store cleared for re-indexing")
                        indexer.resync()
                        reindexing = True
                    except Exception as e:
                        logger.error("Failed to clear and resync: %s", e)
                        return JSONResponse({"error": f"Failed to re-index: {e}"}, status_code=500)
        return {
            "success": True, "reindexing": reindexing,
            "agent_model": sm.get_agent_model(),
            "embedding_model": sm.get_embedding_model(),
        }

    @app.get("/api/settings/knowledge-roots")
    async def settings_get_knowledge_roots(request: Request):
        """Get available roots, agent list, and the user's per-agent knowledge root config."""
        from src.agents.registry import get_agents
        user = request.state.user
        # Get all roots
        all_roots: List[Dict[str, Any]] = []
        if indexer is not None:
            try:
                conn = sqlite3.connect(str(cfg.watcher_db))
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT path, enabled FROM roots ORDER BY path").fetchall()
                conn.close()
                all_roots = [{"path": r["path"], "enabled": bool(r["enabled"])} for r in rows]
            except Exception:
                pass
        agents = get_agents()
        agent_list = [{"name": a["name"], "display_name": a["display_name"]} for a in agents]
        # knowledge_roots is Dict[agent_name, List[str]|null] or None
        return {
            "available_roots": all_roots,
            "agents": agent_list,
            "knowledge_roots": user.knowledge_roots,
        }

    @app.put("/api/settings/knowledge-roots")
    async def settings_put_knowledge_roots(request: Request):
        """Set the current user's per-agent knowledge root selection.

        Body: {"knowledge_roots": {"agent_name": [...paths...] | null, ...}}
        A null value for an agent means "all roots". Omitted agents also default to all.
        Pass null for knowledge_roots to reset (all agents use all roots).
        """
        user = request.state.user
        payload = await request.json()
        kr = payload.get("knowledge_roots")
        if kr is not None and not isinstance(kr, dict):
            return JSONResponse({"error": "knowledge_roots must be a dict or null"}, status_code=400)
        updated = auth_mgr.update_user(user.id, knowledge_roots=kr)
        if not updated:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return {"success": True, "knowledge_roots": updated.knowledge_roots}

    @app.post("/api/settings/pick-folder")
    def pick_folder():
        import subprocess
        import sys

        selected_path = None
        try:
            if sys.platform == "darwin":
                script = '''
                    tell application "System Events"
                        activate
                    end tell
                    set chosenFolder to choose folder with prompt "Select a folder to index:"
                    return POSIX path of chosenFolder
                '''
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
                if result.returncode == 0 and result.stdout.strip():
                    selected_path = result.stdout.strip()
            elif sys.platform == "win32":
                script = '''
                Add-Type -AssemblyName System.Windows.Forms
                $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
                $folderBrowser.Description = "Select a folder to index"
                $folderBrowser.ShowNewFolderButton = $false
                if ($folderBrowser.ShowDialog() -eq "OK") {
                    Write-Output $folderBrowser.SelectedPath
                }
                '''
                result = subprocess.run(["powershell", "-Command", script], capture_output=True, text=True, timeout=120)
                if result.returncode == 0 and result.stdout.strip():
                    selected_path = result.stdout.strip()
            else:
                try:
                    result = subprocess.run(
                        ["zenity", "--file-selection", "--directory", "--title=Select a folder to index"],
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        selected_path = result.stdout.strip()
                except FileNotFoundError:
                    try:
                        result = subprocess.run(
                            ["kdialog", "--getexistingdirectory", os.path.expanduser("~"), "--title", "Select a folder to index"],
                            capture_output=True, text=True, timeout=120,
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            selected_path = result.stdout.strip()
                    except FileNotFoundError:
                        pass
            if selected_path:
                return {"success": True, "path": selected_path}
            return {"success": False, "path": None, "message": "No folder selected"}
        except subprocess.TimeoutExpired:
            return {"success": False, "path": None, "message": "Folder picker timed out"}
        except Exception as e:
            return JSONResponse({"success": False, "path": None, "error": str(e)}, status_code=500)

    @app.post("/api/settings/upload")
    async def handle_upload(request: Request):
        if not cfg.remote_mode or not cfg.uploads_dir:
            return JSONResponse({"error": "File upload is only available in remote mode"}, status_code=403)

        MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

        user = request.state.user
        form = await request.form()
        uploaded_files = []

        subfolder = str(form.get("subfolder", "")).strip()
        subfolder = subfolder.replace("..", "").strip("/\\")
        shared = str(form.get("shared", "")).strip().lower() in ("1", "true", "yes")

        # Admin can upload to the shared_documents folder
        if shared and user.is_admin:
            dest_dir = cfg.uploads_dir / SHARED_DOCS_FOLDER
            if subfolder:
                dest_dir = dest_dir / subfolder
        else:
            # Per-user upload directory
            dest_dir = cfg.uploads_dir / user.username
            if subfolder:
                dest_dir = dest_dir / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)

        supported_exts = {".pdf", ".txt", ".md", ".rst", ".py", ".js", ".ts", ".docx", ".doc"}
        if indexer:
            supported_exts = set(indexer.config.supported_extensions)

        file_items = form.getlist("file")
        for item in file_items:
            if not hasattr(item, "filename") or not item.filename:
                continue
            filename = Path(item.filename).name
            ext = Path(filename).suffix.lower()
            if ext not in supported_exts:
                logger.warning("Upload rejected: unsupported extension %s", ext)
                continue
            file_data = await item.read()
            if len(file_data) > MAX_FILE_SIZE:
                return JSONResponse(
                    {"error": f"File '{filename}' exceeds maximum size of {MAX_FILE_SIZE // (1024*1024)}MB"},
                    status_code=413,
                )
            dest_path = dest_dir / filename
            counter = 1
            while dest_path.exists():
                stem = Path(filename).stem
                dest_path = dest_dir / f"{stem}_{counter}{ext}"
                counter += 1
            dest_path.write_bytes(file_data)
            logger.info("Uploaded file: %s (%d bytes)", dest_path, len(file_data))
            uploaded_files.append({"name": dest_path.name, "path": str(dest_path), "size": len(file_data)})

        if not uploaded_files:
            return JSONResponse({"error": "No valid files uploaded"}, status_code=400)

        if indexer:
            # Auto-register the upload destination as a document root
            try:
                indexer.add_root(dest_dir)
            except Exception:
                pass  # Already registered
            scan_thread = threading.Thread(target=indexer.roots.scan_root, args=(dest_dir,), daemon=True)
            scan_thread.start()

        return {"success": True, "files": uploaded_files, "message": f"Uploaded {len(uploaded_files)} file(s)"}

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    @app.get("/api/agents")
    def agents_list(request: Request):
        from src.agents.registry import get_agents
        agents = get_agents()
        # Merge per-user overrides (custom display_name / avatar_url)
        user = getattr(request.state, "user", None)
        if user and user.agent_overrides:
            for agent in agents:
                override = user.agent_overrides.get(agent["name"])
                if override:
                    if "display_name" in override:
                        agent["display_name"] = override["display_name"]
                    if "avatar_url" in override:
                        agent["avatar_url"] = override["avatar_url"]
        return agents

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    @app.get("/api/documents")
    def documents_list(limit: int = 50, offset: int = 0, search: str = ""):
        where = ""
        params: List[Any] = []
        if search:
            where = "WHERE d.file_path LIKE ?"
            params.append(f"%{search}%")
        with _connect(cfg.vector_db) as vdb:
            total = vdb.execute(f"SELECT COUNT(*) AS c FROM documents d {where}", params).fetchone()["c"]
            rows = vdb.execute(
                f"""SELECT d.file_path, d.parsed_at, d.updated_at,
                          (SELECT e.model_id FROM chunks c JOIN embeddings e ON e.chunk_id = c.chunk_id
                           WHERE c.file_path = d.file_path LIMIT 1) AS embedding_model
                   FROM documents d {where} ORDER BY d.updated_at DESC LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
            docs = []
            for row in rows:
                fp = row["file_path"]
                docs.append({
                    "doc_id": fp, "document_id": generate_document_id(Path(fp)),
                    "filename": _basename(fp), "path": fp,
                    "size": _file_size(fp), "status": _doc_status(fp),
                    "created_at": _to_unix_seconds(row["parsed_at"]),
                    "updated_at": _to_unix_seconds(row["updated_at"]),
                    "embedding_model": row["embedding_model"],
                })
        return {"documents": docs, "total": int(total)}

    @app.get("/api/documents/detail")
    def documents_get(path: str):
        from urllib.parse import unquote
        doc_id = unquote(path)
        with _connect(cfg.vector_db) as vdb:
            row = vdb.execute(
                "SELECT file_path, content_hash, parsed_at, updated_at FROM documents WHERE file_path = ?",
                (doc_id,),
            ).fetchone()
            if not row:
                return JSONResponse({"error": "Document not found"}, status_code=404)
            chunk_count = vdb.execute("SELECT COUNT(*) AS c FROM chunks WHERE file_path = ?", (doc_id,)).fetchone()["c"]
            embedding_model = vdb.execute(
                "SELECT e.model_id FROM chunks c JOIN embeddings e ON e.chunk_id = c.chunk_id WHERE c.file_path = ? LIMIT 1",
                (doc_id,),
            ).fetchone()
        return {
            "doc_id": row["file_path"],
            "document_id": generate_document_id(Path(row["file_path"])),
            "filename": _basename(row["file_path"]),
            "path": row["file_path"],
            "size": _file_size(row["file_path"]),
            "status": _doc_status(row["file_path"]),
            "created_at": _to_unix_seconds(row["parsed_at"]),
            "updated_at": _to_unix_seconds(row["updated_at"]),
            "content_hash": row["content_hash"],
            "page_count": None, "needs_ocr": False,
            "chunk_count": int(chunk_count),
            "embedding_model": embedding_model["model_id"] if embedding_model else None,
        }

    @app.get("/api/documents/chunks")
    def documents_chunks(path: str, limit: int = 100):
        from urllib.parse import unquote
        doc_id = unquote(path)
        with _connect(cfg.vector_db) as vdb:
            total = vdb.execute("SELECT COUNT(*) AS c FROM chunks WHERE file_path = ?", (doc_id,)).fetchone()["c"]
            rows = vdb.execute(
                """SELECT c.rowid AS row_id, c.chunk_id AS chunk_key, c.content AS content,
                          c.chunk_index AS chunk_index, (e.chunk_id IS NOT NULL) AS has_embedding
                   FROM chunks c LEFT JOIN embeddings e ON e.chunk_id = c.chunk_id
                   WHERE c.file_path = ? ORDER BY c.chunk_index ASC LIMIT ?""",
                (doc_id, limit),
            ).fetchall()
            chunks = []
            for row in rows:
                text = row["content"]
                chunks.append({
                    "chunk_id": int(row["row_id"]), "index": int(row["chunk_index"]),
                    "page_start": 0, "page_end": 0,
                    "tokens": len(str(text).split()), "heading": None,
                    "text": text, "has_embedding": bool(row["has_embedding"]),
                })
        return {"chunks": chunks, "total": int(total)}

    @app.get("/api/documents/file")
    def documents_serve_file(path: str):
        from urllib.parse import unquote, quote
        import mimetypes

        file_path = unquote(path)
        if not os.path.isfile(file_path):
            return JSONResponse({"error": "File not found"}, status_code=404)
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = "application/octet-stream"
        filename = os.path.basename(file_path)
        try:
            filename.encode("ascii")
            content_disposition = f'inline; filename="{filename}"'
        except UnicodeEncodeError:
            encoded_filename = quote(filename, safe="")
            content_disposition = f"inline; filename*=UTF-8''{encoded_filename}"
        return Response(
            content=Path(file_path).read_bytes(),
            media_type=content_type,
            headers={"Content-Disposition": content_disposition},
        )

    def _md_to_phrases(content: str) -> List[str]:
        """Strip markdown formatting and split into searchable phrases."""
        import re
        text = content
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\|', ' ', text)
        text = re.sub(r'-{3,}', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        sentences = re.split(r'(?<=[.!?。！？])\s+', text)
        phrases = []
        for s in sentences:
            s = s.strip()
            if len(s) < 8:
                continue
            if len(s) <= 80:
                phrases.append(s)
            else:
                words = s.split()
                current = ""
                for w in words:
                    if current and len(current) + len(w) + 1 > 60:
                        if len(current) >= 8:
                            phrases.append(current)
                        current = w
                    else:
                        current = f"{current} {w}".strip() if current else w
                if current and len(current) >= 8:
                    phrases.append(current)
        return phrases

    def _lookup_chunk_contents(chunk_ids: List[str]) -> Dict[str, str]:
        """Look up chunk contents from DB. Returns {chunk_id: content}."""
        result: Dict[str, str] = {}
        if not chunk_ids:
            return result
        try:
            with _connect(cfg.vector_db) as vdb:
                placeholders = ",".join("?" for _ in chunk_ids)
                rows = vdb.execute(
                    f"SELECT chunk_id, content FROM chunks WHERE chunk_id IN ({placeholders})",
                    chunk_ids,
                ).fetchall()
                for row in rows:
                    result[row["chunk_id"]] = row["content"]
        except Exception:
            pass
        return result

    @app.get("/api/documents/pdf-view")
    def documents_pdf_view(path: str, chunk_ids: str = ""):
        """Serve PDF with highlight annotations on referenced pages.
        
        Fast path: uses page_char_offsets to identify pages, then searches
        phrases only on those specific pages. Falls back to raw file if
        no chunk_ids or no offsets available.
        """
        import bisect

        file_path = path
        if not os.path.isfile(file_path):
            return JSONResponse({"error": "File not found"}, status_code=404)
        if not file_path.lower().endswith(".pdf"):
            return JSONResponse({"error": "Not a PDF file"}, status_code=400)

        ids = [cid.strip() for cid in chunk_ids.split(",") if cid.strip()]
        if not ids:
            return FileResponse(
                file_path,
                media_type="application/pdf",
                headers={"Content-Disposition": "inline"},
            )

        # Look up page_char_offsets and chunk start_offsets for fast page mapping
        page_char_offsets = None
        chunk_offsets: Dict[str, int] = {}
        try:
            db = sqlite3.connect(str(cfg.vector_db))
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT metadata FROM documents WHERE file_path = ?",
                (file_path,),
            ).fetchone()
            if row and row["metadata"]:
                import json as _json
                meta = _json.loads(row["metadata"])
                offsets = meta.get("page_char_offsets")
                if offsets and isinstance(offsets, list) and len(offsets) > 1:
                    page_char_offsets = offsets

            if page_char_offsets:
                placeholders = ",".join("?" for _ in ids)
                rows = db.execute(
                    f"SELECT chunk_id, start_offset, content FROM chunks WHERE chunk_id IN ({placeholders})",
                    ids,
                ).fetchall()
                contents: Dict[str, str] = {}
                for r in rows:
                    chunk_offsets[r["chunk_id"]] = r["start_offset"]
                    contents[r["chunk_id"]] = r["content"]
                db.close()
            else:
                db.close()
                return FileResponse(
                    file_path,
                    media_type="application/pdf",
                    headers={"Content-Disposition": "inline"},
                )
        except Exception:
            return FileResponse(
                file_path,
                media_type="application/pdf",
                headers={"Content-Disposition": "inline"},
            )

        # Map chunks to pages and group phrases by page
        page_phrases: Dict[int, List[str]] = {}  # page_index -> phrases
        for cid in ids:
            offset = chunk_offsets.get(cid)
            if offset is None or cid not in contents:
                continue
            page_idx = bisect.bisect_right(page_char_offsets, offset) - 1
            page_idx = max(0, min(page_idx, len(page_char_offsets) - 1))
            if page_idx not in page_phrases:
                page_phrases[page_idx] = []
            page_phrases[page_idx].extend(_md_to_phrases(contents[cid])[:10])

        if not page_phrases:
            return FileResponse(
                file_path,
                media_type="application/pdf",
                headers={"Content-Disposition": "inline"},
            )

        # Add highlight annotations only on referenced pages
        try:
            import fitz
            doc = fitz.open(file_path)
            for page_idx, phrases in page_phrases.items():
                if page_idx < 0 or page_idx >= len(doc):
                    continue
                pg = doc[page_idx]
                page_rects = []
                for phrase in phrases:
                    try:
                        rects = pg.search_for(phrase)
                        page_rects.extend(rects)
                    except Exception:
                        pass
                if page_rects:
                    try:
                        annot = pg.add_highlight_annot(page_rects)
                        annot.set_colors(stroke=(1, 0.9, 0.2))
                        annot.set_opacity(0.35)
                        annot.update()
                    except Exception:
                        pass

            pdf_bytes = doc.tobytes()
            doc.close()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": "inline",
                    "Cache-Control": "max-age=300",
                },
            )
        except Exception as e:
            logger.error("PDF highlight failed: %s", e, exc_info=True)
            return FileResponse(
                file_path,
                media_type="application/pdf",
                headers={"Content-Disposition": "inline"},
            )

    @app.get("/api/documents/pdf-page-image")
    def documents_pdf_page_image(path: str, page: int = 1, chunk_ids: str = ""):
        """Render a single PDF page as a PNG image with highlight annotations."""
        file_path = path
        if not os.path.isfile(file_path):
            return JSONResponse({"error": "File not found"}, status_code=404)
        if not file_path.lower().endswith(".pdf"):
            return JSONResponse({"error": "Not a PDF file"}, status_code=400)

        try:
            import fitz
        except ImportError:
            return JSONResponse({"error": "PyMuPDF not available"}, status_code=500)

        ids = [cid.strip() for cid in chunk_ids.split(",") if cid.strip()]
        contents = _lookup_chunk_contents(ids)

        try:
            doc = fitz.open(file_path)
            page_index = max(0, min(page - 1, len(doc) - 1))  # 0-based, clamped
            pg = doc[page_index]

            # Highlight matching phrases on this page (limit for speed)
            all_phrases: List[str] = []
            for cid in ids:
                if cid in contents:
                    all_phrases.extend(_md_to_phrases(contents[cid])[:10])

            if all_phrases:
                page_rects = []
                for phrase in all_phrases:
                    try:
                        rects = pg.search_for(phrase)
                        page_rects.extend(rects)
                    except Exception:
                        pass
                if page_rects:
                    try:
                        annot = pg.add_highlight_annot(page_rects)
                        annot.set_colors(stroke=(1, 0.9, 0.2))
                        annot.set_opacity(0.35)
                        annot.update()
                    except Exception:
                        pass

            # Render page to PNG at 1.5x resolution (balance speed vs clarity)
            mat = fitz.Matrix(1.5, 1.5)
            pix = pg.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes("png")
            doc.close()

            return Response(
                content=png_bytes,
                media_type="image/png",
                headers={"Cache-Control": "max-age=300"},
            )
        except Exception as e:
            logger.error("PDF page image failed: %s", e, exc_info=True)
            return JSONResponse({"error": f"PDF page image failed: {e}"}, status_code=500)

    @app.get("/api/documents/pdf-chunk-pages")
    def documents_pdf_chunk_pages(path: str, chunk_ids: str = ""):
        """Return page numbers where each chunk's text is found in the PDF.
        
        Fast path: uses stored page_char_offsets from document metadata
        and chunk start_offset for an instant binary-search lookup.
        Slow fallback: scans PDF pages for phrase matches (old documents).
        """
        import bisect

        file_path = path
        if not os.path.isfile(file_path):
            return JSONResponse({"error": "File not found"}, status_code=404)
        if not file_path.lower().endswith(".pdf"):
            return JSONResponse({"error": "Not a PDF file"}, status_code=400)

        ids = [cid.strip() for cid in chunk_ids.split(",") if cid.strip()]
        if not ids:
            return {"pages": {}, "total_pages": 0}

        # Try fast path: look up page_char_offsets from document metadata
        page_char_offsets = None
        total_pages = 0
        try:
            db = sqlite3.connect(str(cfg.vector_db))
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT metadata FROM documents WHERE file_path = ?",
                (file_path,),
            ).fetchone()
            if row and row["metadata"]:
                import json as _json
                meta = _json.loads(row["metadata"])
                offsets = meta.get("page_char_offsets")
                if offsets and isinstance(offsets, list) and len(offsets) > 1:
                    page_char_offsets = offsets
                    total_pages = meta.get("page_count", len(offsets))

            if page_char_offsets:
                # Fast path: binary search chunk start_offset against page boundaries
                placeholders = ",".join("?" for _ in ids)
                rows = db.execute(
                    f"SELECT chunk_id, start_offset FROM chunks WHERE chunk_id IN ({placeholders})",
                    ids,
                ).fetchall()
                chunk_offsets = {r["chunk_id"]: r["start_offset"] for r in rows}
                db.close()

                chunk_pages: Dict[str, int] = {}
                for cid in ids:
                    offset = chunk_offsets.get(cid)
                    if offset is None:
                        chunk_pages[cid] = 1
                        continue
                    page_idx = bisect.bisect_right(page_char_offsets, offset) - 1
                    page_idx = max(0, min(page_idx, len(page_char_offsets) - 1))
                    chunk_pages[cid] = page_idx + 1  # 1-based
                return {"pages": chunk_pages, "total_pages": total_pages}
            else:
                db.close()
        except Exception:
            pass

        # Slow fallback for documents without page_char_offsets
        try:
            import fitz
        except ImportError:
            return JSONResponse({"error": "PyMuPDF not available"}, status_code=500)

        contents = _lookup_chunk_contents(ids)

        try:
            doc = fitz.open(file_path)
            chunk_pages = {}

            for cid in ids:
                if cid not in contents:
                    chunk_pages[cid] = 1
                    continue
                phrases = _md_to_phrases(contents[cid])[:5]
                best_page = 0
                best_count = 0
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    count = 0
                    for phrase in phrases:
                        try:
                            rects = page.search_for(phrase)
                            count += len(rects)
                        except Exception:
                            pass
                    if count > best_count:
                        best_count = count
                        best_page = page_num
                        if best_count >= 3:
                            break
                if best_count == 0:
                    chunk_pages[cid] = 1
                else:
                    chunk_pages[cid] = best_page + 1
            total = len(doc)
            doc.close()
            return {"pages": chunk_pages, "total_pages": total}
        except Exception as e:
            logger.error("PDF chunk pages failed: %s", e, exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.delete("/api/documents/file")
    def delete_uploaded_file(request: Request, path: str = ""):
        doc_path = path.strip()
        if not cfg.remote_mode or not cfg.uploads_dir:
            return JSONResponse({"error": "File deletion is only available in remote mode"}, status_code=403)
        try:
            user = request.state.user
            file_path = Path(doc_path).resolve()
            # Users can only delete files in their own upload folder (admins can delete any)
            user_uploads = (cfg.uploads_dir / user.username).resolve()
            uploads_resolved = cfg.uploads_dir.resolve()
            if not user.is_admin:
                if not str(file_path).startswith(str(user_uploads)):
                    return JSONResponse({"error": "Can only delete your own uploaded files"}, status_code=403)
            else:
                if not str(file_path).startswith(str(uploads_resolved)):
                    return JSONResponse({"error": "Can only delete files in the uploads directory"}, status_code=403)
            if not file_path.exists():
                return JSONResponse({"error": "File not found"}, status_code=404)
            if not file_path.is_file():
                return JSONResponse({"error": "Path is not a file"}, status_code=400)
            if indexer:
                removed = indexer._store.remove_document(file_path)
                logger.info("Removed %d document entries for: %s", removed, file_path)
            file_path.unlink()
            logger.info("Deleted uploaded file: %s", file_path)
            return {"success": True, "message": f"Deleted {file_path.name}"}
        except Exception as e:
            logger.error("Delete failed: %s", e, exc_info=True)
            return JSONResponse({"error": f"Delete failed: {e}"}, status_code=500)

    @app.get("/api/documents/context")
    def documents_context(path: str, chunk_id: str, window: int = 2):
        from urllib.parse import unquote
        from .store import VectorStore
        from .config import VectorStoreConfig

        doc_path = unquote(path)
        try:
            config = VectorStoreConfig(db_path=cfg.vector_db)
            store = VectorStore(config)
            chunks = store.get_chunks_for_document(Path(doc_path))
            store.close()
            if not chunks:
                return JSONResponse({"status": "error", "error_message": f"No chunks found for: {doc_path}"}, status_code=404)
            target_idx = None
            for i, c in enumerate(chunks):
                if c.chunk.chunk_id == chunk_id:
                    target_idx = i
                    break
            if target_idx is None:
                return JSONResponse({"status": "error", "error_message": f"Chunk not found: {chunk_id}"}, status_code=404)
            start = max(0, target_idx - window)
            end = min(len(chunks), target_idx + window + 1)
            context = []
            for i in range(start, end):
                context.append({
                    "chunk_id": chunks[i].chunk.chunk_id,
                    "content": chunks[i].chunk.content,
                    "is_target": i == target_idx,
                    "position": i - target_idx,
                })
            return {"status": "success", "file_path": doc_path, "context": context, "total_chunks_in_doc": len(chunks)}
        except Exception as e:
            return JSONResponse({"status": "error", "error_message": str(e)}, status_code=500)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @app.post("/api/search")
    async def search_chunks(request: Request):
        payload = await request.json()
        query = str(payload.get("query", "")).strip()
        top_k = _safe_int(payload.get("top_k", 10), 10)
        file_filter = payload.get("file_filter")
        agent_name = payload.get("agent_name")
        if not query:
            return JSONResponse({"error": "Missing query"}, status_code=400)
        try:
            if indexer is None:
                return JSONResponse({"status": "error", "error_message": "Indexer not available"}, status_code=503)
            disabled = _get_disabled_roots(indexer)
            exclude, inc_under, inc_roots = _get_user_search_filters(request.state.user, auth_mgr, cfg, disabled, agent_name=agent_name)
            results = indexer.search(query, top_k=top_k, exclude_root_paths=exclude, file_filter=file_filter, include_under=inc_under, include_roots=inc_roots)
            formatted = [{
                "file_path": str(r.document_path), "chunk_id": r.chunk.chunk_id,
                "content": r.chunk.content, "score": round(r.score, 4),
            } for r in results]
            return {"status": "success", "results": formatted, "total_found": len(formatted)}
        except Exception as e:
            logger.error("search_chunks error: %s", e, exc_info=True)
            return JSONResponse({"status": "error", "error_message": str(e)}, status_code=500)

    @app.post("/api/search/documents")
    async def search_documents(request: Request):
        payload = await request.json()
        query = str(payload.get("query", "")).strip()
        top_k = _safe_int(payload.get("top_k", 5), 5)
        agent_name = payload.get("agent_name")
        if not query:
            return JSONResponse({"error": "Missing query"}, status_code=400)
        try:
            if indexer is None:
                return JSONResponse({"status": "error", "error_message": "Indexer not available"}, status_code=503)
            disabled = _get_disabled_roots(indexer)
            exclude, inc_under, inc_roots = _get_user_search_filters(request.state.user, auth_mgr, cfg, disabled, agent_name=agent_name)
            results = indexer.search_documents(query, top_k=top_k, exclude_root_paths=exclude, include_under=inc_under, include_roots=inc_roots)
            formatted = [{
                "document_id": r.document_id, "file_path": str(r.file_path),
                "filename": _basename(str(r.file_path)), "file_type": r.file_type,
                "chunk_count": r.chunk_count, "score": round(r.score, 4),
            } for r in results]
            return {"status": "success", "documents": formatted, "total_found": len(formatted)}
        except Exception as e:
            return JSONResponse({"status": "error", "error_message": str(e)}, status_code=500)

    @app.post("/api/search/keyword")
    async def search_keyword(request: Request):
        payload = await request.json()
        query = str(payload.get("query", "")).strip()
        top_k = _safe_int(payload.get("top_k", 10), 10)
        agent_name = payload.get("agent_name")
        if not query:
            return JSONResponse({"error": "Missing query"}, status_code=400)
        try:
            if indexer is None:
                return JSONResponse({"status": "error", "error_message": "Indexer not available"}, status_code=503)
            disabled = _get_disabled_roots(indexer)
            exclude, inc_under, inc_roots = _get_user_search_filters(request.state.user, auth_mgr, cfg, disabled, agent_name=agent_name)
            results = indexer.keyword_search(query, top_k=top_k, exclude_root_paths=exclude, include_under=inc_under, include_roots=inc_roots)
            formatted = [{
                "file_path": str(r.document_path), "chunk_id": r.chunk.chunk_id,
                "content": r.chunk.content, "score": round(r.score, 4),
            } for r in results]
            return {"status": "success", "results": formatted, "total_found": len(formatted)}
        except Exception as e:
            return JSONResponse({"status": "error", "error_message": str(e)}, status_code=500)

    # ------------------------------------------------------------------
    # Chat helpers (legacy /api/chat endpoint)
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    async def chat_proxy(request: Request):
        payload = await request.json()
        message = payload.get("message", "")
        agent = payload.get("agent", "doc_qa_agent")
        session_id = payload.get("session_id")
        user_id = request.state.user.username
        if not message:
            return JSONResponse({"error": "Missing message"}, status_code=400)

        agent_api = cfg.agent_api_url

        async with httpx.AsyncClient(timeout=300) as client:
            if not session_id:
                try:
                    resp = await client.post(f"{agent_api}/apps/{agent}/users/{user_id}/sessions", json={})
                    session_data = resp.json()
                    session_id = session_data.get("id", "default_session")
                except Exception as e:
                    return JSONResponse({"error": f"Failed to create session: {e}"}, status_code=502)

            adk_payload = {
                "appName": agent, "userId": user_id, "sessionId": session_id,
                "newMessage": {"role": "user", "parts": [{"text": message}]},
                "streaming": True,
            }

            async def stream():
                async with httpx.AsyncClient(timeout=300) as sc:
                    async with sc.stream("POST", f"{agent_api}/run_sse", json=adk_payload) as resp:
                        async for line in resp.aiter_lines():
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if data_str:
                                    try:
                                        data = json.loads(data_str)
                                        parts = data.get("content", {}).get("parts", [])
                                        for part in parts:
                                            if "text" in part:
                                                out = json.dumps({
                                                    "type": "content", "content": part["text"],
                                                    "session_id": session_id,
                                                })
                                                yield f"data: {out}\n\n"
                                    except json.JSONDecodeError:
                                        pass
                            elif line.strip():
                                yield line + "\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/chat/sessions")
    async def chat_create_session(request: Request):
        payload = await request.json()
        agent = payload.get("agent", "doc_qa_agent")
        user_id = request.state.user.username
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{cfg.agent_api_url}/apps/{agent}/users/{user_id}/sessions", json={})
                session_data = resp.json()
                return {"session_id": session_data.get("id"), "agent": agent}
        except Exception as e:
            return JSONResponse({"error": f"Failed to create session: {e}"}, status_code=502)

    # ------------------------------------------------------------------
    # ADK reverse proxy (sessions, run_sse)
    # ------------------------------------------------------------------

    @app.post("/api/run_sse")
    async def proxy_run_sse(request: Request):
        # Inject authenticated userId into SSE payload
        try:
            payload = json.loads(await request.body())
            payload["userId"] = request.state.user.username
            body = json.dumps(payload).encode("utf-8")
        except Exception:
            body = await request.body()
        agent_api = cfg.agent_api_url

        async def stream():
            async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
                async with client.stream(
                    "POST", f"{agent_api}/run_sse",
                    content=body,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "Connection": "close",
        })

    @app.api_route("/api/apps/{path:path}", methods=["GET", "POST", "DELETE"])
    async def proxy_adk_apps(path: str, request: Request):
        agent_api = cfg.agent_api_url
        url = f"{agent_api}/apps/{path}"
        body = None
        if request.method == "POST":
            body = await request.body()

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.request(
                    request.method, url,
                    content=body,
                    headers={"Content-Type": "application/json"} if body else {},
                )
                return Response(content=resp.content, status_code=resp.status_code,
                                media_type="application/json")
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ------------------------------------------------------------------
    # API docs (HTML)
    # ------------------------------------------------------------------

    def _serve_docs():
        return HTMLResponse(_API_DOCS_HTML)
    app.get("/docs")(_serve_docs)
    app.get("/docs/")(_serve_docs)

    # ------------------------------------------------------------------
    # Static files / SPA fallback
    # ------------------------------------------------------------------

    if cfg.web_dist_path and cfg.web_dist_path.exists():
        # Serve asset files with long cache
        assets_dir = cfg.web_dist_path / "assets"
        if assets_dir.exists():
            from starlette.staticfiles import StaticFiles
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

        @app.get("/{path:path}")
        def spa_fallback(path: str):
            import mimetypes
            web_dist = cfg.web_dist_path
            if not web_dist:
                return JSONResponse({"error": "Not found"}, status_code=404)

            if path == "" or path == "/":
                file_path = web_dist / "index.html"
            else:
                file_path = (web_dist / path).resolve()
                if not str(file_path).startswith(str(web_dist.resolve())):
                    return JSONResponse({"error": "Forbidden"}, status_code=403)

            if not file_path.exists():
                if "." not in file_path.name:
                    file_path = web_dist / "index.html"
                else:
                    return JSONResponse({"error": "Not found"}, status_code=404)

            if not file_path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)

            content_type, _ = mimetypes.guess_type(str(file_path))
            if not content_type:
                content_type = "application/octet-stream"

            cache = "no-cache" if file_path.name == "index.html" else "max-age=31536000"
            return Response(
                content=file_path.read_bytes(),
                media_type=content_type,
                headers={"Cache-Control": cache},
            )

    return app


# ---------------------------------------------------------------------------
# Command helpers (used by route handlers)
# ---------------------------------------------------------------------------

def _queue_root_command(indexer: Optional["IndexerProcess"], cfg: IndexerAPIConfig, root_path: Path, action: str) -> Optional[str]:
    if action not in {"add", "remove"}:
        return "Invalid action"
    if indexer:
        if action == "add":
            try:
                added = indexer.add_root(root_path)
            except RootOverlapError as e:
                return str(e)
            if not added:
                return "Folder already added"
        else:
            indexer.remove_root(root_path)
        return None
    if WatcherProcess is None or WatcherConfig is None:
        return "Watcher integration unavailable"
    if not WatcherProcess.check_running(cfg.watcher_db):
        return "Watcher is not running. Start the indexer process first."
    watcher = WatcherProcess(config=WatcherConfig(db_path=cfg.watcher_db))
    if action == "add":
        watcher.add_root(root_path)
    else:
        watcher.remove_root(root_path)
    return None


def _queue_system_command(indexer: Optional["IndexerProcess"], cfg: IndexerAPIConfig, action: str) -> Optional[str]:
    if action not in {"resync", "integrity_check"}:
        return "Invalid action"
    if indexer:
        if action == "resync":
            indexer.resync()
        else:
            indexer.integrity_check()
        return None
    if WatcherProcess is None or WatcherConfig is None:
        return "Watcher integration unavailable"
    if not WatcherProcess.check_running(cfg.watcher_db):
        return "Watcher is not running. Start the indexer process first."
    watcher = WatcherProcess(config=WatcherConfig(db_path=cfg.watcher_db))
    if action == "resync":
        watcher.resync()
    else:
        watcher.integrity_check()
    return None


# ---------------------------------------------------------------------------
# HTML for /docs endpoint
# ---------------------------------------------------------------------------

_API_DOCS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Indexer API Documentation</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }
        h2 { color: #007bff; margin-top: 30px; }
        .endpoint { background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .method { display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; margin-right: 10px; font-size: 14px; }
        .get { background: #61affe; color: white; }
        .post { background: #49cc90; color: white; }
        .delete { background: #f93e3e; color: white; }
        .path { font-family: monospace; font-size: 16px; color: #333; }
        .desc { color: #666; margin: 10px 0; }
        .params { margin-top: 15px; }
        .params h4 { margin: 0 0 10px 0; font-size: 14px; color: #333; }
        .param { background: #f8f9fa; padding: 8px 12px; margin: 5px 0; border-radius: 4px; font-family: monospace; font-size: 13px; }
        .param-name { color: #d63384; }
        .param-type { color: #6c757d; }
        code { background: #e9ecef; padding: 2px 6px; border-radius: 3px; font-size: 13px; }
        .example { background: #263238; color: #aed581; padding: 15px; border-radius: 4px; overflow-x: auto; margin-top: 10px; }
        .example pre { margin: 0; font-size: 13px; }
    </style>
</head>
<body>
<div class="container">
    <h1>Indexer REST API</h1>
    <p>Base URL: <code>http://localhost:8001</code></p>

    <h2>Search Endpoints</h2>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="path">/api/search</span>
        <p class="desc">Search document chunks semantically using embeddings.</p>
        <div class="params">
            <h4>Request Body (JSON)</h4>
            <div class="param"><span class="param-name">query</span>: <span class="param-type">string</span> - Search query text (required)</div>
            <div class="param"><span class="param-name">top_k</span>: <span class="param-type">integer</span> - Max results (default: 10)</div>
            <div class="param"><span class="param-name">file_filter</span>: <span class="param-type">string</span> - Filter by file path pattern (optional)</div>
        </div>
        <div class="example"><pre>curl -X POST http://localhost:8001/api/search \\
  -H "Content-Type: application/json" \\
  -d '{"query": "machine learning", "top_k": 5}'</pre></div>
    </div>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="path">/api/search/documents</span>
        <p class="desc">Search at document level using document embeddings.</p>
        <div class="params">
            <h4>Request Body (JSON)</h4>
            <div class="param"><span class="param-name">query</span>: <span class="param-type">string</span> - Search query text (required)</div>
            <div class="param"><span class="param-name">top_k</span>: <span class="param-type">integer</span> - Max documents (default: 5)</div>
        </div>
    </div>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="path">/api/search/keyword</span>
        <p class="desc">Full-text keyword search using BM25 ranking.</p>
        <div class="params">
            <h4>Request Body (JSON)</h4>
            <div class="param"><span class="param-name">query</span>: <span class="param-type">string</span> - Keywords or phrase (required)</div>
            <div class="param"><span class="param-name">top_k</span>: <span class="param-type">integer</span> - Max results (default: 10)</div>
        </div>
    </div>

    <h2>Document Endpoints</h2>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/documents</span>
        <p class="desc">List all indexed documents.</p>
        <div class="params">
            <h4>Query Parameters</h4>
            <div class="param"><span class="param-name">limit</span>: <span class="param-type">integer</span> - Max results (default: 50)</div>
            <div class="param"><span class="param-name">offset</span>: <span class="param-type">integer</span> - Pagination offset (default: 0)</div>
            <div class="param"><span class="param-name">search</span>: <span class="param-type">string</span> - Filter by file path</div>
        </div>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/documents/detail</span>
        <p class="desc">Get details for a specific document.</p>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/documents/chunks</span>
        <p class="desc">Get chunks for a specific document.</p>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/documents/context</span>
        <p class="desc">Get context around a specific chunk.</p>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/documents/file</span>
        <p class="desc">Serve the actual file content (PDF, etc.).</p>
    </div>

    <h2>Settings Endpoints</h2>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/settings/roots</span>
        <p class="desc">List watched root directories.</p>
    </div>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="path">/api/settings/roots</span>
        <p class="desc">Add a new root directory to watch.</p>
    </div>

    <div class="endpoint">
        <span class="method delete">DELETE</span>
        <span class="path">/api/settings/roots</span>
        <p class="desc">Remove a watched root directory.</p>
    </div>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="path">/api/settings/pick-folder</span>
        <p class="desc">Open native folder picker dialog.</p>
    </div>

    <h2>Dashboard Endpoints</h2>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/dashboard/stats</span>
        <p class="desc">Get indexer statistics (document count, chunk count, etc.).</p>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/dashboard/health</span>
        <p class="desc">Get system health status.</p>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <span class="path">/api/dashboard/activity</span>
        <p class="desc">Get recent activity log.</p>
    </div>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="path">/api/dashboard/resync</span>
        <p class="desc">Trigger a full resync of all documents.</p>
    </div>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="path">/api/dashboard/integrity-check</span>
        <p class="desc">Run integrity check on the index.</p>
    </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Service wrapper (replaces old HTTPServer-based service)
# ---------------------------------------------------------------------------

class IndexerAPIService:
    """Wrapper to run the FastAPI server via uvicorn in a background thread."""

    def __init__(
        self,
        host: str,
        port: int,
        cfg: IndexerAPIConfig,
        indexer: Optional["IndexerProcess"] = None,
    ):
        self.host = host
        self.port = port
        self.cfg = cfg
        self.indexer = indexer
        self._thread: Optional[threading.Thread] = None
        self._server: Any = None

    def start(self) -> None:
        import uvicorn

        app = create_app(self.cfg, self.indexer)

        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
            self._server = None


if __name__ == "__main__":
    raise SystemExit("Run via indexer process.")
