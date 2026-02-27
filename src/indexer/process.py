"""
Main indexer process.
"""

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .models import Document, Chunk, EmbeddedChunk, SearchResult, DocumentSearchResult, IndexerEvent, IndexerEventType
from .config import IndexerConfig, ChunkingConfig
from .exceptions import IndexerError, ParseError, UnsupportedFileTypeError
from .parsers import create_default_registry, ParserRegistry
from .chunker import Chunker
from .embeddings import create_embedder, BaseEmbedder
from .store import VectorStore
from .activity import ActivityLogger, DatabaseLogHandler
from .roots import RootManager
from .api_server import IndexerAPIConfig, IndexerAPIService

# Import watcher if available
try:
    from src.watcher import WatcherProcess, WatcherConfig, FileEvent, EventType
    WATCHER_AVAILABLE = True
except ImportError:
    try:
        from watcher import WatcherProcess, WatcherConfig, FileEvent, EventType
        WATCHER_AVAILABLE = True
    except ImportError:
        WATCHER_AVAILABLE = False
        WatcherProcess = None
        WatcherConfig = None
        FileEvent = None
        EventType = None


logger = logging.getLogger(__name__)




class IndexerProcess:
    """
    Main indexer process.
    
    Consumes file events from watcher and maintains searchable index.
    """
    
    def __init__(
        self,
        config: Optional[IndexerConfig] = None,
        parser_registry: Optional[ParserRegistry] = None,
        embedder: Optional[BaseEmbedder] = None,
        initial_roots: Optional[List[Path]] = None,
    ):
        """
        Initialize indexer process.
        
        Args:
            config: Indexer configuration
            parser_registry: Custom parser registry
            embedder: Custom embedder
            initial_roots: Initial root directories to watch
        """
        self.config = config or IndexerConfig()
        self._initial_roots = initial_roots or []
        
        logger.debug(f"IndexerProcess initializing...")
        logger.debug(f"  watcher_db_path: {self.config.watcher_db_path}")
        logger.debug(f"  vector_db_path: {self.config.vector_db_path}")
        logger.debug(f"  web_dist_path: {self.config.web_dist_path}")
        
        # Activity logging
        self._activity = ActivityLogger(self.config.watcher_db_path)
        
        # Set up database logging handler for system logs
        self._setup_db_logging()
        
        # Initialize components
        logger.debug("Creating parser registry...")
        self._parser_registry = parser_registry or create_default_registry()
        logger.debug(f"Parser registry created with {len(self._parser_registry)} parsers")
        for ext in self._parser_registry.supported_extensions():
            logger.debug(f"  Registered extension: {ext}")
        
        self._chunker = Chunker(self.config.chunking)
        self._embedder = embedder
        logger.debug("Creating vector store...")
        self._store = VectorStore(self.config.get_vector_store_config())
        logger.debug("Vector store created")
        
        # Watcher integration
        self._watcher: Optional[WatcherProcess] = None
        
        # Processing state
        self._running = False
        self._stop_event = threading.Event()
        self._process_thread: Optional[threading.Thread] = None
        self._failed_files: Set[Path] = set()
        self._lock = threading.Lock()
        api_host = os.environ.get("INDEXER_API_HOST", "127.0.0.1")
        api_port = int(os.environ.get("INDEXER_API_PORT", "8001"))
        # Root manager (initialized before API service since it needs index_file)
        self.roots = RootManager(
            watcher_db_path=self.config.watcher_db_path,
            store=self._store,
            config=self.config,
            activity=self._activity,
            watcher=self._watcher,
            index_file_fn=self.index_file,
            stop_event=self._stop_event,
        )
        
        self._api_service = IndexerAPIService(
            api_host,
            api_port,
            IndexerAPIConfig(
                vector_db=self.config.vector_db_path,
                watcher_db=self.config.watcher_db_path,
                web_dist_path=self.config.web_dist_path,
                remote_mode=self.config.remote_mode,
                uploads_dir=self.config.uploads_dir,
            ),
            indexer=self,
        )
    
    def _setup_db_logging(self) -> None:
        """Set up database logging handler to capture system logs."""
        try:
            # Add database handler to root logger to capture all logs
            db_handler = DatabaseLogHandler(self.config.watcher_db_path)
            db_handler.setLevel(logging.INFO)  # Only capture INFO and above
            db_handler.setFormatter(logging.Formatter('%(message)s'))
            
            # Add to root logger
            root_logger = logging.getLogger()
            # Remove any existing DatabaseLogHandler to avoid duplicates
            for handler in root_logger.handlers[:]:
                if isinstance(handler, DatabaseLogHandler):
                    root_logger.removeHandler(handler)
            root_logger.addHandler(db_handler)
            
            logger.info("System logging initialized")
        except Exception as e:
            logger.warning(f"Failed to setup database logging: {e}")
    
    def _get_embedder(self) -> BaseEmbedder:
        """Get or create embedder."""
        if self._embedder is None:
            self._embedder = create_embedder(
                provider=self.config.embedding.provider,
                model=self.config.embedding.model_id,
                api_key=self.config.embedding.get_api_key(),
                api_base=self.config.embedding.get_api_base(),
                http_proxy=self.config.embedding.get_http_proxy(),
                https_proxy=self.config.embedding.get_https_proxy(),
                timeout=self.config.embedding.timeout_seconds,
                max_retries=self.config.embedding.max_retries,
                batch_size=self.config.embedding.batch_size,
            )
        return self._embedder
    
    def start(self) -> None:
        """Start the indexer process (blocking)."""
        self._running = True
        self._stop_event.clear()
        
        # Initialize watcher if available
        if WATCHER_AVAILABLE:
            watcher_config = WatcherConfig(db_path=self.config.watcher_db_path)
            self._watcher = WatcherProcess(config=watcher_config, initial_roots=self._initial_roots)
            self._watcher.start_async()
            self.roots._watcher = self._watcher
            
            # Log watched roots
            if self._initial_roots:
                logger.info(f"Watching {len(self._initial_roots)} root(s)")
                for root in self._initial_roots:
                    logger.info(f"  - {root}")
        
        if self._api_service:
            try:
                self._api_service.start()
                logger.info(
                    "Indexer API listening on http://%s:%s",
                    self._api_service.host,
                    self._api_service.port,
                )
            except OSError as exc:
                logger.error("Failed to start Indexer API: %s", exc)

        logger.info("Indexer started")
        
        # Scan existing files in watched roots
        if self._initial_roots:
            self._scan_existing_files()
        
        try:
            self._process_loop()
        finally:
            self._running = False
            if self._watcher:
                self._watcher.stop()
            if self._api_service:
                self._api_service.stop()
    
    def start_async(self) -> None:
        """Start the indexer process in background thread."""
        if self._running:
            return
        
        self._process_thread = threading.Thread(target=self.start, daemon=True)
        self._process_thread.start()
    
    def stop(self) -> None:
        """Stop the indexer process."""
        self._stop_event.set()
        self._running = False
        
        if self._process_thread and self._process_thread.is_alive():
            self._process_thread.join(timeout=5.0)
        
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._api_service:
            self._api_service.stop()

        logger.info("Indexer stopped")
    
    def _log_activity(self, activity_type: str, message: str, path: str = None) -> None:
        """Log an activity to the activity_log table."""
        self._activity.log(activity_type, message, path)

    def add_root(self, root: Path) -> bool:
        """Add a root directory to watch."""
        return self.roots.add_root(root)
    
    def remove_root(self, root: Path) -> None:
        """Remove a root directory from watching."""
        self.roots.remove_root(root)

    def set_root_enabled(self, root: Path, enabled: bool) -> bool:
        """Enable or disable a root directory."""
        return self.roots.set_root_enabled(root, enabled)

    def get_disabled_root_paths(self) -> List[str]:
        """Get paths of all disabled roots."""
        return self.roots.get_disabled_root_paths()

    def resync(self) -> None:
        """Queue a full resync via the watcher."""
        self.roots.resync()

    def integrity_check(self) -> None:
        """Queue an integrity check via the watcher."""
        self.roots.integrity_check()

    def build_integrity_report(self, max_items: int = 10) -> Dict[str, Any]:
        """Build an integrity report comparing indexed files vs watched roots."""
        return self.roots.build_integrity_report(max_items=max_items)
    
    def get_roots(self) -> List[Path]:
        """Get current watched roots."""
        return self.roots.get_roots()
    
    def _scan_existing_files(self) -> None:
        """Scan and index existing files in watched roots."""
        logger.info("Scanning existing files...")
        
        indexed_count = 0
        skipped_count = 0
        
        for root in self._initial_roots:
            if not root.exists():
                continue
            
            for file_path in root.rglob("*"):
                if self._stop_event.is_set():
                    break
                
                if not file_path.is_file():
                    continue
                
                if not self.config.is_supported(file_path):
                    continue
                
                try:
                    result = self.index_file(file_path)
                    if result.event_type == IndexerEventType.INDEXED and result.chunk_count > 0:
                        indexed_count += 1
                        logger.info(f"Indexed: {file_path} ({result.chunk_count} chunks)")
                    else:
                        skipped_count += 1
                except Exception as e:
                    logger.error(f"Failed to index {file_path}: {e}")
        
        logger.info(f"Initial scan complete: {indexed_count} indexed, {skipped_count} skipped")
    
    def _process_loop(self) -> None:
        """Main processing loop."""
        while not self._stop_event.is_set():
            try:
                if self._watcher:
                    # Get events from watcher
                    events = self._watcher.get_pending_events(max_count=10)
                    
                    for event in events:
                        try:
                            self._process_event(event)
                        except Exception as e:
                            logger.error(f"Error processing event {event}: {e}")
                
                # Sleep briefly
                time.sleep(self.config.process_interval_ms / 1000.0)
                
            except Exception as e:
                logger.error(f"Error in process loop: {e}")
                time.sleep(1.0)
    
    def _process_event(self, event) -> None:
        """
        Process a file event.
        
        Args:
            event: FileEvent from watcher
        """
        if not WATCHER_AVAILABLE:
            return
        
        file_path = Path(event.path) if isinstance(event.path, str) else event.path
        
        logger.info(f"Processing event: {event.event_type.value} - {file_path}")
        
        # Handle root events first (they don't need file type check)
        if event.event_type == EventType.ROOT_ADDED:
            self._handle_root_added(file_path)
            return
        elif event.event_type == EventType.ROOT_REMOVED:
            self._handle_root_removed(file_path)
            return
        elif event.event_type == EventType.RESYNC:
            self._handle_resync()
            return
        elif event.event_type == EventType.INTEGRITY_CHECK:
            self._handle_integrity_check()
            return
        
        # Check if file type is supported
        if not self.config.is_supported(file_path):
            logger.debug(f"Skipping unsupported file type: {file_path}")
            return
        
        if event.event_type == EventType.ADD:
            result = self._handle_add(file_path)
            logger.info(f"Indexed: {file_path} ({result.chunk_count} chunks)")
        elif event.event_type == EventType.UPDATE:
            result = self._handle_update(file_path)
            logger.info(f"Updated: {file_path} ({result.chunk_count} chunks)")
        elif event.event_type == EventType.DELETE:
            result = self._handle_delete(file_path)
            logger.info(f"Removed: {file_path}")
        elif event.event_type == EventType.MOVE:
            result = self._handle_move(file_path, event.old_path)
            logger.info(f"Moved: {event.old_path} -> {file_path}")
    
    def _handle_add(self, file_path: Path) -> IndexerEvent:
        """Handle file add event."""
        return self.index_file(file_path)
    
    def _handle_update(self, file_path: Path) -> IndexerEvent:
        """Handle file update event."""
        return self.index_file(file_path)
    
    def _handle_delete(self, file_path: Path) -> IndexerEvent:
        """Handle file delete event."""
        return self.remove_file(file_path)
    
    def _handle_move(self, new_path: Path, old_path: Optional[Path]) -> IndexerEvent:
        """Handle file move event."""
        if old_path:
            # Remove old path
            self._store.remove_document(old_path)
        
        # Index at new path
        return self.index_file(new_path)
    
    def _handle_root_added(self, root_path: Path) -> None:
        """Handle root added event from watcher."""
        self.roots.scan_root(root_path)
    
    def _handle_root_removed(self, root_path: Path) -> None:
        """Handle root removed event from watcher."""
        removed_count = self._store.remove_documents_under_path(root_path)
        logger.info(f"Removed {removed_count} documents from root: {root_path}")
    
    def _handle_resync(self) -> None:
        """Handle resync event from watcher."""
        self.roots.handle_resync()
    
    def _handle_integrity_check(self) -> None:
        """Handle integrity check event from watcher."""
        self.roots.handle_integrity_check()
    
    # Public API
    
    def index_file(self, file_path: Path) -> IndexerEvent:
        """
        Index a single file.
        
        Args:
            file_path: Path to file
            
        Returns:
            IndexerEvent describing the result
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        file_path = file_path.resolve()
        logger.debug(f"index_file called: {file_path}")
        
        try:
            # Check if file exists
            if not file_path.exists():
                logger.debug(f"File not found: {file_path}")
                return IndexerEvent(
                    event_type=IndexerEventType.FAILED,
                    file_path=file_path,
                    timestamp=datetime.now(),
                    error_message="File not found",
                )
            
            # Parse document
            logger.debug(f"Parsing document: {file_path}")
            try:
                document = self._parser_registry.parse(file_path)
                logger.debug(f"Parsed successfully: {file_path}, content_hash={document.content_hash}, content_length={len(document.content)}")
            except Exception as parse_error:
                logger.error(f"Parse error for {file_path}: {parse_error}", exc_info=True)
                raise
            
            # Check if unchanged
            if self._store.document_exists(file_path, document.content_hash):
                logger.debug(f"Skipping unchanged file: {file_path}")
                return IndexerEvent(
                    event_type=IndexerEventType.INDEXED,
                    file_path=file_path,
                    timestamp=datetime.now(),
                    chunk_count=0,
                )
            
            # Remove old chunks if updating
            self._store.remove_document(file_path)
            
            # Chunk document
            logger.debug(f"Chunking document: {file_path}")
            chunks = self._chunker.chunk(document)
            logger.debug(f"Created {len(chunks)} chunks for {file_path}")
            
            if not chunks:
                # Store document with no chunks
                logger.debug(f"No chunks created, storing document only: {file_path}")
                self._store.add_document(document)
                return IndexerEvent(
                    event_type=IndexerEventType.INDEXED,
                    file_path=file_path,
                    timestamp=datetime.now(),
                    chunk_count=0,
                )
            
            # Generate embeddings
            logger.debug(f"Getting embedder for {file_path}")
            try:
                embedder = self._get_embedder()
                logger.debug(f"Embedder: {embedder.__class__.__name__}, model_id={embedder.model_id}")
            except Exception as embed_init_error:
                logger.error(f"Failed to get embedder: {embed_init_error}", exc_info=True)
                raise
            
            texts = [chunk.content for chunk in chunks]
            logger.debug(f"Generating embeddings for {len(texts)} chunks...")
            try:
                embeddings = embedder.embed(texts)
                logger.debug(f"Generated {len(embeddings)} embeddings")
            except Exception as embed_error:
                logger.error(f"Embedding generation failed for {file_path}: {embed_error}", exc_info=True)
                raise
            
            # Create embedded chunks
            embedded_chunks = []
            now = datetime.now()
            for chunk, embedding in zip(chunks, embeddings):
                embedded_chunk = EmbeddedChunk(
                    chunk=chunk,
                    embedding=embedding,
                    model_id=embedder.model_id,
                    embedded_at=now,
                )
                embedded_chunks.append(embedded_chunk)
            
            # Store document and chunks
            self._store.add_document(document)
            self._store.add_chunks(embedded_chunks)
            
            # Generate and store document-level embedding
            doc_embedding = self._generate_document_embedding(
                document, chunks, embeddings, embedder
            )
            if doc_embedding is not None:
                self._store.add_document_embedding(
                    document_id=document.document_id,
                    embedding=doc_embedding,
                    model_id=embedder.model_id,
                    chunk_count=len(chunks),
                )
            
            # Remove from failed set
            with self._lock:
                self._failed_files.discard(file_path)
            
            logger.info(f"Indexed {file_path} with {len(chunks)} chunks")
            
            return IndexerEvent(
                event_type=IndexerEventType.INDEXED,
                file_path=file_path,
                timestamp=datetime.now(),
                chunk_count=len(chunks),
            )
            
        except UnsupportedFileTypeError as e:
            logger.debug(f"Unsupported file type: {file_path}")
            return IndexerEvent(
                event_type=IndexerEventType.FAILED,
                file_path=file_path,
                timestamp=datetime.now(),
                error_message=str(e),
            )
            
        except Exception as e:
            logger.error(f"Failed to index {file_path}: {e}")
            
            with self._lock:
                self._failed_files.add(file_path)
            
            return IndexerEvent(
                event_type=IndexerEventType.FAILED,
                file_path=file_path,
                timestamp=datetime.now(),
                error_message=str(e),
            )
    
    def remove_file(self, file_path: Path) -> IndexerEvent:
        """
        Remove a file from the index.
        
        Args:
            file_path: Path to file
            
        Returns:
            IndexerEvent describing the result
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        chunk_count = self._store.remove_document(file_path)
        
        logger.info(f"Removed {file_path} ({chunk_count} chunks)")
        
        return IndexerEvent(
            event_type=IndexerEventType.REMOVED,
            file_path=file_path,
            timestamp=datetime.now(),
            chunk_count=chunk_count,
        )
    
    def _generate_document_embedding(
        self,
        document: Document,
        chunks: List[Chunk],
        chunk_embeddings: List[List[float]],
        embedder: BaseEmbedder,
    ) -> Optional[List[float]]:
        """
        Generate document-level embedding.
        
        If document content fits within model's max token limit, embed full text.
        Otherwise, average the chunk embeddings.
        
        Args:
            document: The document
            chunks: List of chunks
            chunk_embeddings: Pre-computed chunk embeddings
            embedder: Embedder to use
            
        Returns:
            Document embedding vector, or None if no chunks
        """
        import numpy as np
        
        if not chunk_embeddings:
            return None
        
        # Estimate tokens conservatively (~3 chars per token to avoid API errors)
        estimated_tokens = len(document.content) // 3
        
        if estimated_tokens <= embedder.max_tokens * 0.9:  # 10% safety margin
            # Document fits in context - embed full text directly
            try:
                return embedder.embed_single(document.content)
            except Exception as e:
                logger.warning(f"Failed to embed full document, falling back to average: {e}")
        
        # Document too long - use average of chunk embeddings
        embeddings_array = np.array(chunk_embeddings, dtype=np.float32)
        
        # Weighted average by chunk length
        weights = np.array([len(chunk.content) for chunk in chunks], dtype=np.float32)
        weights = weights / weights.sum()
        
        doc_embedding = np.average(embeddings_array, axis=0, weights=weights)
        
        # Normalize for cosine similarity
        norm = np.linalg.norm(doc_embedding)
        if norm > 0:
            doc_embedding = doc_embedding / norm
        
        return doc_embedding.tolist()
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_paths: Optional[List[Path]] = None,
        min_score: float = 0.0,
        exclude_root_paths: Optional[List[str]] = None,
        file_filter: Optional[str] = None,
        include_under: Optional[str] = None,
        include_roots: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """
        Search indexed documents.
        
        Args:
            query: Search query
            top_k: Number of results
            filter_paths: Optional path filter
            min_score: Minimum similarity score
            exclude_root_paths: Optional root paths whose documents to exclude
            file_filter: Optional file pattern (e.g. '*.pdf' or substring)
            include_under: Scoped directory for include-based filtering
            include_roots: Allowed root prefixes within include_under
            
        Returns:
            List of search results
        """
        # Generate query embedding
        embedder = self._get_embedder()
        query_embedding = embedder.embed_single(query)
        
        # Search
        return self._store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_paths=filter_paths,
            min_score=min_score,
            exclude_root_paths=exclude_root_paths,
            file_filter=file_filter,
            include_under=include_under,
            include_roots=include_roots,
        )
    
    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        filter_paths: Optional[List[Path]] = None,
        exclude_root_paths: Optional[List[str]] = None,
        include_under: Optional[str] = None,
        include_roots: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """
        Full-text keyword search using BM25.
        
        Args:
            query: Keywords or phrase to search for
            top_k: Number of results
            filter_paths: Optional path filter
            exclude_root_paths: Optional root paths whose documents to exclude
            include_under: Scoped directory for include-based filtering
            include_roots: Allowed root prefixes within include_under
            
        Returns:
            List of search results
        """
        return self._store.keyword_search(
            query=query,
            top_k=top_k,
            filter_paths=filter_paths,
            exclude_root_paths=exclude_root_paths,
            include_under=include_under,
            include_roots=include_roots,
        )
    
    def search_documents(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        exclude_root_paths: Optional[List[str]] = None,
        include_under: Optional[str] = None,
        include_roots: Optional[List[str]] = None,
    ) -> List[DocumentSearchResult]:
        """
        Document-level semantic search.
        
        Args:
            query: Search query
            top_k: Number of documents to return
            min_score: Minimum similarity score
            exclude_root_paths: Optional root paths whose documents to exclude
            include_under: Scoped directory for include-based filtering
            include_roots: Allowed root prefixes within include_under
            
        Returns:
            List of DocumentSearchResult
        """
        embedder = self._get_embedder()
        query_embedding = embedder.embed_single(query)
        
        return self._store.search_documents(
            query_embedding=query_embedding,
            top_k=top_k,
            min_score=min_score,
            exclude_root_paths=exclude_root_paths,
            include_under=include_under,
            include_roots=include_roots,
        )
    
    def get_context_for_query(
        self,
        query: str,
        max_chunks: int = 5,
        max_chars: int = 8000,
    ) -> str:
        """
        Get formatted context for LLM query.
        
        Args:
            query: Search query
            max_chunks: Maximum chunks to include
            max_chars: Maximum characters
            
        Returns:
            Formatted context string
        """
        results = self.search(query, top_k=max_chunks)
        
        if not results:
            return ""
        
        context_parts = []
        total_chars = 0
        
        for result in results:
            chunk_text = f"[Source: {result.document_path.name}]\n{result.chunk.content}\n"
            
            if total_chars + len(chunk_text) > max_chars:
                # Truncate
                remaining = max_chars - total_chars
                if remaining > 100:
                    chunk_text = chunk_text[:remaining] + "..."
                    context_parts.append(chunk_text)
                break
            
            context_parts.append(chunk_text)
            total_chars += len(chunk_text)
        
        return "\n---\n".join(context_parts)
    
    def get_stats(self) -> dict:
        """Get indexer statistics."""
        store_stats = self._store.get_stats()
        
        with self._lock:
            failed_count = len(self._failed_files)
        
        return {
            **store_stats,
            "running": self._running,
            "failed_files": failed_count,
        }
    
    def close(self) -> None:
        """Close the indexer."""
        self.stop()
        
        if self._store:
            self._store.close()
        
        if self._embedder and hasattr(self._embedder, 'close'):
            self._embedder.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
