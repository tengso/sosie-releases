"""
Common tools shared across agents.

All tools access the vector store through the indexer REST API.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import logging

from google.adk.tools import ToolContext

from src.indexer.auth import AuthManager

logger = logging.getLogger(__name__)



# Indexer API configuration
INDEXER_API_HOST = os.environ.get("INDEXER_API_HOST", "localhost")
INDEXER_API_PORT = int(os.environ.get("INDEXER_API_PORT", "8001"))


def _indexer_url(path: str) -> str:
    """Build indexer API URL."""
    return f"http://{INDEXER_API_HOST}:{INDEXER_API_PORT}{path}"


def _service_token() -> Optional[str]:
    """Get the internal service token for agent→indexer auth bypass."""
    return os.environ.get("SOSIE_SERVICE_TOKEN")


def _get_user_id(tool_context: Optional[ToolContext]) -> Optional[str]:
    """Extract user_id from tool context for request scoping."""
    if tool_context and tool_context.user_id:
        return str(tool_context.user_id).strip() or None
    return None


def _http_get(url: str, timeout: float = 30.0, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Make HTTP GET request and return JSON response."""
    req = Request(url, method="GET")
    req.add_header("Content-Type", "application/json")
    token = _service_token()
    if token:
        req.add_header("X-Service-Token", token)
        if user_id:
            req.add_header("X-User-Id", user_id)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(url: str, data: Dict[str, Any], timeout: float = 60.0, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Make HTTP POST request and return JSON response."""
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    token = _service_token()
    if token:
        req.add_header("X-Service-Token", token)
        if user_id:
            req.add_header("X-User-Id", user_id)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_auth_db_path() -> Path:
    """Return default auth DB path by platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    return base / "Sosie" / "auth.db"


def _resolve_auth_db_path() -> Path:
    """Resolve auth DB path for agent tools."""
    configured = os.environ.get("SOSIE_AUTH_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()

    local_data = (Path.cwd() / "data" / "auth.db").resolve()
    if local_data.exists():
        return local_data

    return _default_auth_db_path().resolve()


def get_user_contact(tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """Return current user's username, display name, and email."""
    user_id = ""
    if tool_context and tool_context.user_id:
        user_id = str(tool_context.user_id).strip()
    logger.info("get_user_contact: user=%s", user_id)

    if not user_id:
        return {
            "status": "error",
            "error_message": "User context is unavailable",
        }

    auth_db = _resolve_auth_db_path()
    if not auth_db.exists():
        return {
            "status": "error",
            "error_message": f"Auth database not found: {auth_db}",
        }

    try:
        auth_mgr = AuthManager(auth_db)
        user = auth_mgr.get_user_by_username(user_id)
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e),
        }

    if user is None:
        return {
            "status": "error",
            "error_message": f"User '{user_id}' not found",
        }

    return {
        "status": "success",
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
    }


def search_chunks(
    query: str, 
    top_k: int = 10,
    file_filter: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Search indexed document chunks for information relevant to the query.
    Supports filtering by file path pattern.
    
    Args:
        query: The search query describing what information to find
        top_k: Maximum number of results to return (default: 10)
        file_filter: Optional file path pattern to filter results (e.g., "*.pdf" or "reports/")
    
    Returns:
        dict: Search results containing:
            - status: 'success' or 'error'
            - results: List of matching document chunks with file paths, content, and chunk_id
            - total_found: Number of results found
    """
    uid = _get_user_id(tool_context)
    logger.info("search_chunks: query=%r, top_k=%d, user=%s, file_filter=%s", query, top_k, uid, file_filter)
    try:
        payload = {"query": query, "top_k": top_k}
        if file_filter:
            payload["file_filter"] = file_filter
        if tool_context:
            payload["agent_name"] = tool_context.agent_name
        
        result = _http_post(_indexer_url("/api/search"), payload, user_id=uid)
        logger.info("search_chunks: status=%s, total_found=%s", result.get("status"), result.get("total_found"))
        return result
        
    except Exception as e:
        logger.error("search_chunks error: %s", e)
        return {
            "status": "error",
            "error_message": str(e)
        }


def search_documents(
    query: str,
    top_k: int = 5,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Find documents most relevant to the query using document-level semantic search.
    Use this BEFORE chunk-level search to identify which documents to explore in depth.
    This searches document summaries/embeddings for a high-level match.
    
    Args:
        query: The search query describing what documents to find
        top_k: Maximum number of documents to return (default: 5)
    
    Returns:
        dict: Contains list of relevant documents with scores and metadata
    """
    uid = _get_user_id(tool_context)
    logger.info("search_documents: query=%r, top_k=%d, user=%s", query, top_k, uid)
    try:
        payload = {"query": query, "top_k": top_k}
        if tool_context:
            payload["agent_name"] = tool_context.agent_name
        result = _http_post(_indexer_url("/api/search/documents"), payload, user_id=uid)
        logger.info("search_documents: status=%s, total_found=%s", result.get("status"), result.get("total_found"))
        return result
        
    except Exception as e:
        logger.error("search_documents error: %s", e)
        return {
            "status": "error",
            "error_message": str(e)
        }


def keyword_search(
    query: str,
    top_k: int = 10,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Full-text keyword search using BM25 ranking.
    Use this when you need to find exact words or phrases in documents.
    Unlike semantic search, this matches exact keywords and is useful for:
    - Finding specific terms, names, or codes
    - Searching for exact phrases
    - When semantic meaning is less important than exact word matches
    
    Args:
        query: Keywords or phrase to search for
        top_k: Maximum number of results to return (default: 10)
    
    Returns:
        dict: Search results containing matched chunks with file paths and content
    """
    uid = _get_user_id(tool_context)
    logger.info("keyword_search: query=%r, top_k=%d, user=%s", query, top_k, uid)
    try:
        payload = {"query": query, "top_k": top_k}
        if tool_context:
            payload["agent_name"] = tool_context.agent_name
        result = _http_post(_indexer_url("/api/search/keyword"), payload, user_id=uid)
        logger.info("keyword_search: status=%s, total_found=%s", result.get("status"), result.get("total_found"))
        return result
        
    except Exception as e:
        logger.error("keyword_search error: %s", e)
        return {
            "status": "error",
            "error_message": str(e)
        }


def get_document_context(
    file_path: str,
    chunk_id: str,
    context_window: int = 2,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Get expanded context around a specific chunk in a document.
    Useful for understanding the surrounding context of a finding.
    
    Args:
        file_path: Path to the document
        chunk_id: ID of the chunk to get context for
        context_window: Number of chunks before and after to include (default: 2)
    
    Returns:
        dict: Contains expanded context with surrounding chunks
    """
    from urllib.parse import quote
    
    uid = _get_user_id(tool_context)
    logger.info("get_document_context: file=%s, chunk=%s, window=%d, user=%s", file_path, chunk_id, context_window, uid)
    try:
        url = _indexer_url(f"/api/documents/context?path={quote(file_path)}&chunk_id={chunk_id}&window={context_window}")
        result = _http_get(url, user_id=uid)
        logger.info("get_document_context: status=%s", result.get("status"))
        return result
        
    except Exception as e:
        logger.error("get_document_context error: %s", e)
        return {
            "status": "error",
            "error_message": str(e)
        }


def list_available_documents(
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    List all indexed documents with metadata.
    Use this to understand what documents are available for research.
    
    Returns:
        dict: Contains list of documents with their paths and chunk counts
    """
    uid = _get_user_id(tool_context)
    logger.info("list_available_documents: user=%s", uid)
    try:
        data = _http_get(_indexer_url("/api/documents?limit=1000"), user_id=uid)
        
        documents = []
        for doc in data.get("documents", []):
            documents.append({
                "file_path": doc.get("path", ""),
                "filename": doc.get("filename", ""),
                "chunk_count": 0,  # Not available from this endpoint
            })
        
        # Group by extension
        by_type = {}
        for doc in documents:
            ext = Path(doc["file_path"]).suffix.lower() or "unknown"
            if ext not in by_type:
                by_type[ext] = 0
            by_type[ext] += 1
        
        logger.info("list_available_documents: total_count=%d", len(documents))
        return {
            "status": "success",
            "documents": documents,
            "total_count": len(documents),
            "by_type": by_type,
        }
        
    except Exception as e:
        logger.error("list_available_documents error: %s", e)
        return {
            "status": "error",
            "error_message": str(e)
        }


def multi_query_search(
    queries: List[str],
    top_k_per_query: int = 5,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Execute multiple search queries and combine results.
    Use this to search for different aspects of a research topic.
    
    Args:
        queries: List of search queries to execute
        top_k_per_query: Number of results per query (default: 5)
    
    Returns:
        dict: Combined and deduplicated results from all queries
    """
    uid = _get_user_id(tool_context)
    logger.info("multi_query_search: queries=%r, top_k_per_query=%d, user=%s", queries, top_k_per_query, uid)
    try:
        all_results = {}  # Use dict to dedupe by chunk_id
        
        for query in queries:
            payload = {"query": query, "top_k": top_k_per_query}
            if tool_context:
                payload["agent_name"] = tool_context.agent_name
            data = _http_post(_indexer_url("/api/search"), payload, user_id=uid)
            
            if data.get("status") != "success":
                continue
            
            for result in data.get("results", []):
                chunk_id = result.get("chunk_id", "")
                if chunk_id not in all_results:
                    all_results[chunk_id] = {
                        "file_path": result.get("file_path", ""),
                        "chunk_id": chunk_id,
                        "content": result.get("content", ""),
                        "best_score": result.get("score", 0),
                        "matched_queries": [query],
                    }
                else:
                    all_results[chunk_id]["matched_queries"].append(query)
                    all_results[chunk_id]["best_score"] = max(
                        all_results[chunk_id]["best_score"], 
                        result.get("score", 0)
                    )
        
        # Sort by number of query matches, then by score
        sorted_results = sorted(
            all_results.values(),
            key=lambda x: (len(x["matched_queries"]), x["best_score"]),
            reverse=True
        )
        
        logger.info("multi_query_search: total_unique_chunks=%d, queries_executed=%d", len(sorted_results), len(queries))
        return {
            "status": "success",
            "results": sorted_results,
            "total_unique_chunks": len(sorted_results),
            "queries_executed": len(queries),
        }
        
    except Exception as e:
        logger.error("multi_query_search error: %s", e)
        return {
            "status": "error",
            "error_message": str(e)
        }


def send_email(email_recipient: str, email_subject: str, email_body: str):
    """
    This function sends an email to recipient

    Args:
        email_recipient: the recipient of the email
        email_subject: the subject of the email
        email_body: the body of the email
    """

    from exchangelib import Message, HTMLBody

    recipients = email_recipient.strip('').strip(';').split(';')
    account = get_account()
    m = Message(
        account=account, 
        folder=account.sent, 
        subject=email_subject, 
        body=HTMLBody(email_body),
        to_recipients=recipients
    )
    m.send_and_save()
    logger.info("send_email: to=%s, subject=%r", email_recipient, email_subject)
    return True


def get_account():
    from exchangelib import Account, NoVerifyHTTPAdapter, Credentials, Configuration, BaseProtocol

    # FIXME: should get sender and password from environment variables
    sender = 'smart_job@htisec.com'
    sender_password = 'SmtHti$2627'

    BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
    ews_endpoint = 'https://mail.htisec.com/EWS/Exchange.asmx'
    creds = Credentials(username=sender, password=sender_password)
    config = Configuration(credentials=creds, service_endpoint=ews_endpoint)
    account = Account(primary_smtp_address=sender, credentials=creds, config=config, autodiscover=False)
    return account
