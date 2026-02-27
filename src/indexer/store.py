"""
Vector store for the indexer package.
"""

import json
import logging
import sqlite3
import struct
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

import numpy as np

from .models import Document, Chunk, EmbeddedChunk, SearchResult, DocumentSearchResult
from .config import VectorStoreConfig
from .exceptions import StoreError, DocumentNotFoundError


class VectorStore:
    """SQLite-based vector storage with similarity search."""
    
    def __init__(self, config: Optional[VectorStoreConfig] = None):
        """
        Initialize vector store.
        
        Args:
            config: Store configuration
        """
        self.config = config or VectorStoreConfig()
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False
        
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        self._conn = sqlite3.connect(
            str(self.config.db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for better concurrency
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Enable foreign keys for CASCADE deletes
        self._conn.execute("PRAGMA foreign_keys=ON")
        
        # Create tables
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL UNIQUE,
                content_hash TEXT NOT NULL,
                file_type TEXT NOT NULL,
                metadata TEXT,
                parsed_at TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
            );
            
            CREATE TABLE IF NOT EXISTS embeddings (
                chunk_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                model_id TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                embedded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
            );
            
            CREATE TABLE IF NOT EXISTS document_embeddings (
                document_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                model_id TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                embedded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_documents_file_path ON documents(file_path);
            CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path);
            CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model_id);
        """)
        
        # Create FTS table for full-text search
        try:
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    content,
                    chunk_id UNINDEXED,
                    content='chunks',
                    content_rowid='rowid'
                )
            """)
        except sqlite3.OperationalError:
            pass
        
        # Create triggers for FTS sync
        try:
            self._conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, content, chunk_id)
                    VALUES (NEW.rowid, NEW.content, NEW.chunk_id);
                END;
                
                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content, chunk_id)
                    VALUES ('delete', OLD.rowid, OLD.content, OLD.chunk_id);
                END;
                
                CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content, chunk_id)
                    VALUES ('delete', OLD.rowid, OLD.content, OLD.chunk_id);
                    INSERT INTO chunks_fts(rowid, content, chunk_id)
                    VALUES (NEW.rowid, NEW.content, NEW.chunk_id);
                END;
            """)
        except sqlite3.OperationalError:
            pass
    
    def _check_closed(self) -> None:
        """Check if store is closed."""
        if self._closed:
            raise StoreError("Store is closed")
    
    # Document operations
    
    def add_document(self, document: Document) -> None:
        """
        Add or update document metadata.
        
        Args:
            document: Document to add
        """
        self._check_closed()
        
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO documents (document_id, file_path, content_hash, file_type, metadata, parsed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                document.document_id,
                str(document.file_path),
                document.content_hash,
                document.file_type,
                json.dumps(document.metadata),
                document.parsed_at.isoformat(),
                datetime.now().isoformat(),
            ))
    
    def remove_document(self, file_path: Path) -> int:
        """
        Remove document and all its chunks.
        
        Args:
            file_path: Path to document
            
        Returns:
            Number of chunks removed
        """
        self._check_closed()
        
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        with self._lock:
            # Get chunk count before deletion
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE file_path = ?",
                (str(file_path),)
            )
            chunk_count = cursor.fetchone()[0]
            
            # Delete document (cascades to chunks and embeddings)
            self._conn.execute(
                "DELETE FROM documents WHERE file_path = ?",
                (str(file_path),)
            )
            
            return chunk_count
    
    def remove_documents_under_path(self, root_path: Path) -> int:
        """
        Remove all documents under a given path.
        
        Args:
            root_path: Root path - all documents with paths starting with this will be removed
            
        Returns:
            Number of documents removed
        """
        self._check_closed()
        
        if isinstance(root_path, str):
            root_path = Path(root_path)
        
        path_prefix = str(root_path) + "/"
        
        with self._lock:
            # Get document count before deletion
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE file_path LIKE ?",
                (path_prefix + "%",)
            )
            doc_count = cursor.fetchone()[0]
            
            # Delete all documents under this path (cascades to chunks and embeddings)
            self._conn.execute(
                "DELETE FROM documents WHERE file_path LIKE ?",
                (path_prefix + "%",)
            )
            
            return doc_count
    
    def get_document(self, file_path: Path) -> Optional[Document]:
        """
        Get document by path.
        
        Args:
            file_path: Path to document
            
        Returns:
            Document or None if not found
        """
        self._check_closed()
        
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM documents WHERE file_path = ?",
                (str(file_path),)
            )
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            return Document(
                file_path=Path(row["file_path"]),
                content="",  # Content not stored in DB
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                content_hash=row["content_hash"],
                parsed_at=datetime.fromisoformat(row["parsed_at"]),
                file_type=row["file_type"],
                document_id=row["document_id"],
            )
    
    def get_all_file_paths(self) -> List[Path]:
        """
        Get all indexed file paths.
        
        Returns:
            List of file paths for all indexed documents
        """
        self._check_closed()
        
        with self._lock:
            cursor = self._conn.execute("SELECT file_path FROM documents")
            return [Path(row["file_path"]) for row in cursor.fetchall()]
    
    def document_exists(self, file_path: Path, content_hash: Optional[str] = None) -> bool:
        """
        Check if document exists (optionally with same hash).
        
        Args:
            file_path: Path to document
            content_hash: Optional hash to match
            
        Returns:
            True if document exists (with matching hash if provided)
        """
        self._check_closed()
        
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        with self._lock:
            if content_hash:
                cursor = self._conn.execute(
                    "SELECT 1 FROM documents WHERE file_path = ? AND content_hash = ?",
                    (str(file_path), content_hash)
                )
            else:
                cursor = self._conn.execute(
                    "SELECT 1 FROM documents WHERE file_path = ?",
                    (str(file_path),)
                )
            
            return cursor.fetchone() is not None
    
    # Chunk operations
    
    def add_chunks(self, chunks: List[EmbeddedChunk]) -> None:
        """
        Add embedded chunks.
        
        Args:
            chunks: List of embedded chunks
        """
        self._check_closed()
        
        if not chunks:
            return
        
        with self._lock:
            for ec in chunks:
                chunk = ec.chunk
                
                # Insert chunk
                self._conn.execute("""
                    INSERT OR REPLACE INTO chunks 
                    (chunk_id, document_id, file_path, content, start_offset, end_offset, chunk_index, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chunk.chunk_id,
                    chunk.document_id,
                    str(chunk.document_path),
                    chunk.content,
                    chunk.start_offset,
                    chunk.end_offset,
                    chunk.chunk_index,
                    json.dumps(chunk.metadata),
                ))
                
                # Insert embedding
                embedding_blob = self._pack_embedding(ec.embedding)
                self._conn.execute("""
                    INSERT OR REPLACE INTO embeddings
                    (chunk_id, embedding, model_id, dimensions, embedded_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    chunk.chunk_id,
                    embedding_blob,
                    ec.model_id,
                    len(ec.embedding),
                    ec.embedded_at.isoformat(),
                ))
    
    def get_chunks_for_document(self, file_path: Path) -> List[EmbeddedChunk]:
        """
        Get all chunks for a document.
        
        Args:
            file_path: Path to document
            
        Returns:
            List of embedded chunks
        """
        self._check_closed()
        
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        with self._lock:
            cursor = self._conn.execute("""
                SELECT c.*, e.embedding, e.model_id, e.embedded_at
                FROM chunks c
                JOIN embeddings e ON c.chunk_id = e.chunk_id
                WHERE c.file_path = ?
                ORDER BY c.chunk_index
            """, (str(file_path),))
            
            results = []
            for row in cursor.fetchall():
                chunk = Chunk(
                    chunk_id=row["chunk_id"],
                    document_path=Path(row["file_path"]),
                    content=row["content"],
                    start_offset=row["start_offset"],
                    end_offset=row["end_offset"],
                    chunk_index=row["chunk_index"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                )
                
                embedded_chunk = EmbeddedChunk(
                    chunk=chunk,
                    embedding=self._unpack_embedding(row["embedding"]),
                    model_id=row["model_id"],
                    embedded_at=datetime.fromisoformat(row["embedded_at"]),
                )
                results.append(embedded_chunk)
            
            return results
    
    # Search operations
    
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter_paths: Optional[List[Path]] = None,
        min_score: float = 0.0,
        exclude_root_paths: Optional[List[str]] = None,
        file_filter: Optional[str] = None,
        include_under: Optional[str] = None,
        include_roots: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """
        Semantic search over chunks.
        
        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            filter_paths: Optional list of paths to filter by
            min_score: Minimum similarity score
            exclude_root_paths: Optional root paths whose documents to exclude
            file_filter: Optional file pattern (e.g. '*.pdf' or substring)
            include_under: Scoped directory for include-based filtering
            include_roots: Allowed root prefixes within include_under
            
        Returns:
            List of search results
        """
        self._check_closed()
        
        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm > 0:
            query_vec = query_vec / query_norm
        
        with self._lock:
            # Build query
            where_clauses = []
            params: List[Any] = []
            if filter_paths:
                path_placeholders = ",".join("?" * len(filter_paths))
                where_clauses.append(f"c.file_path IN ({path_placeholders})")
                params.extend(str(p) for p in filter_paths)
            if exclude_root_paths:
                for rp in exclude_root_paths:
                    where_clauses.append("c.file_path NOT LIKE ?")
                    params.append(rp.rstrip("/") + "/%")
            if include_under and include_roots:
                or_parts = ["c.file_path NOT LIKE ?"]
                params.append(include_under.rstrip("/") + "/%")
                for ir in include_roots:
                    or_parts.append("c.file_path LIKE ?")
                    params.append(ir.rstrip("/") + "/%")
                where_clauses.append(f"({' OR '.join(or_parts)})")
            if file_filter:
                if file_filter.startswith("*."):
                    where_clauses.append("c.file_path LIKE ?")
                    params.append("%" + file_filter[1:])
                else:
                    where_clauses.append("c.file_path LIKE ?")
                    params.append("%" + file_filter + "%")
            
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            cursor = self._conn.execute(f"""
                SELECT c.*, e.embedding, e.model_id
                FROM chunks c
                JOIN embeddings e ON c.chunk_id = e.chunk_id
                {where_sql}
            """, params)
            
            # Calculate similarities
            results = []
            for row in cursor.fetchall():
                embedding = self._unpack_embedding(row["embedding"])
                doc_vec = np.array(embedding, dtype=np.float32)
                doc_norm = np.linalg.norm(doc_vec)
                if doc_norm > 0:
                    doc_vec = doc_vec / doc_norm
                
                # Cosine similarity
                score = float(np.dot(query_vec, doc_vec))
                
                if score >= min_score:
                    chunk = Chunk(
                        chunk_id=row["chunk_id"],
                        document_path=Path(row["file_path"]),
                        content=row["content"],
                        start_offset=row["start_offset"],
                        end_offset=row["end_offset"],
                        chunk_index=row["chunk_index"],
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    )
                    
                    result = SearchResult(
                        chunk=chunk,
                        score=score,
                        document_path=Path(row["file_path"]),
                    )
                    results.append(result)
            
            # Sort by score and return top_k
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]
    
    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize query for FTS5 MATCH syntax."""
        # Remove FTS5 special operators that cause OperationalError
        # Split into tokens, wrap each in double quotes for exact matching
        tokens = query.split()
        if not tokens:
            return '""'
        # Quote each token to avoid syntax issues with special chars
        sanitized = ' '.join(f'"{t.replace(chr(34), "")}"' for t in tokens)
        return sanitized

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
        Full-text keyword search.
        
        Tries FTS5 first for speed, then falls back to LIKE-based search
        for CJK text and queries that FTS5 cannot handle.
        
        Args:
            query: Search query
            top_k: Number of results
            filter_paths: Optional path filter
            exclude_root_paths: Optional root paths whose documents to exclude
            include_under: Scoped directory for include-based filtering
            include_roots: Allowed root prefixes within include_under
            
        Returns:
            List of search results
        """
        self._check_closed()
        
        with self._lock:
            # Try FTS5 first
            results = self._keyword_search_fts(query, top_k, filter_paths, exclude_root_paths, include_under, include_roots)
            if results:
                return results
            
            # Fallback to LIKE-based search (handles CJK and special chars)
            return self._keyword_search_like(query, top_k, filter_paths, exclude_root_paths, include_under, include_roots)

    def _keyword_search_fts(
        self,
        query: str,
        top_k: int,
        filter_paths: Optional[List[Path]],
        exclude_root_paths: Optional[List[str]] = None,
        include_under: Optional[str] = None,
        include_roots: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """FTS5 MATCH search. Returns empty list on failure."""
        fts_query = self._sanitize_fts_query(query)
        try:
            where_parts = ["chunks_fts MATCH ?"]
            params: List[Any] = [fts_query]
            if filter_paths:
                path_placeholders = ",".join("?" * len(filter_paths))
                where_parts.append(f"c.file_path IN ({path_placeholders})")
                params.extend(str(p) for p in filter_paths)
            if exclude_root_paths:
                for rp in exclude_root_paths:
                    where_parts.append("c.file_path NOT LIKE ?")
                    params.append(rp.rstrip("/") + "/%")
            if include_under and include_roots:
                or_parts = ["c.file_path NOT LIKE ?"]
                params.append(include_under.rstrip("/") + "/%")
                for ir in include_roots:
                    or_parts.append("c.file_path LIKE ?")
                    params.append(ir.rstrip("/") + "/%")
                where_parts.append(f"({' OR '.join(or_parts)})")
            params.append(top_k)
            
            where_sql = " AND ".join(where_parts)
            cursor = self._conn.execute(f"""
                SELECT c.*, bm25(chunks_fts) as score
                FROM chunks_fts
                JOIN chunks c ON chunks_fts.chunk_id = c.chunk_id
                WHERE {where_sql}
                ORDER BY score
                LIMIT ?
            """, params)
            
            return self._rows_to_search_results(cursor.fetchall())
            
        except sqlite3.OperationalError as e:
            logger.warning("FTS keyword_search failed for query %r: %s", query, e)
            return []

    @staticmethod
    def _expand_cjk_variants(text: str) -> List[str]:
        """Return simplified and traditional Chinese variants of the text.
        
        Returns a list of unique variants (may be 1 if no conversion changes anything).
        """
        try:
            from opencc import OpenCC
            variants = {text}
            # Simplified → Traditional
            variants.add(OpenCC("s2t").convert(text))
            # Traditional → Simplified
            variants.add(OpenCC("t2s").convert(text))
            return list(variants)
        except ImportError:
            return [text]

    def _keyword_search_like(
        self,
        query: str,
        top_k: int,
        filter_paths: Optional[List[Path]],
        exclude_root_paths: Optional[List[str]] = None,
        include_under: Optional[str] = None,
        include_roots: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """LIKE-based fallback search for CJK and special characters.
        
        Automatically expands Chinese queries to match both simplified
        and traditional character variants.
        """
        tokens = query.split()
        if not tokens:
            return []
        
        # For each token, expand to simplified/traditional variants
        conditions = []
        params: List[Any] = []
        for token in tokens:
            variants = self._expand_cjk_variants(token)
            if len(variants) == 1:
                conditions.append("content LIKE ?")
                params.append(f"%{variants[0]}%")
            else:
                # OR across variants, AND across tokens
                or_parts = " OR ".join(["content LIKE ?"] * len(variants))
                conditions.append(f"({or_parts})")
                params.extend(f"%{v}%" for v in variants)
        
        where = " AND ".join(conditions)
        
        if filter_paths:
            path_placeholders = ",".join("?" * len(filter_paths))
            where += f" AND file_path IN ({path_placeholders})"
            params.extend(str(p) for p in filter_paths)
        if exclude_root_paths:
            for rp in exclude_root_paths:
                where += " AND file_path NOT LIKE ?"
                params.append(rp.rstrip("/") + "/%")
        if include_under and include_roots:
            or_parts = ["file_path NOT LIKE ?"]
            params.append(include_under.rstrip("/") + "/%")
            for ir in include_roots:
                or_parts.append("file_path LIKE ?")
                params.append(ir.rstrip("/") + "/%")
            where += f" AND ({' OR '.join(or_parts)})"
        
        params.append(top_k)
        
        try:
            cursor = self._conn.execute(f"""
                SELECT * FROM chunks
                WHERE {where}
                ORDER BY chunk_index ASC
                LIMIT ?
            """, params)
            
            return self._rows_to_search_results(cursor.fetchall(), default_score=1.0)
            
        except sqlite3.Error as e:
            logger.warning("LIKE keyword_search failed for query %r: %s", query, e)
            return []

    def _rows_to_search_results(
        self,
        rows: list,
        default_score: Optional[float] = None,
    ) -> List[SearchResult]:
        """Convert DB rows to SearchResult list."""
        results = []
        for row in rows:
            chunk = Chunk(
                chunk_id=row["chunk_id"],
                document_path=Path(row["file_path"]),
                content=row["content"],
                start_offset=row["start_offset"],
                end_offset=row["end_offset"],
                chunk_index=row["chunk_index"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )
            score = default_score if default_score is not None else abs(row["score"])
            result = SearchResult(
                chunk=chunk,
                score=score,
                document_path=Path(row["file_path"]),
            )
            results.append(result)
        return results
    
    # Document embedding operations
    
    def add_document_embedding(
        self,
        document_id: str,
        embedding: List[float],
        model_id: str,
        chunk_count: int,
    ) -> None:
        """
        Add or update document-level embedding.
        
        Args:
            document_id: Document ID
            embedding: Document embedding vector
            model_id: Embedding model used
            chunk_count: Number of chunks used to generate embedding
        """
        self._check_closed()
        
        with self._lock:
            embedding_blob = self._pack_embedding(embedding)
            self._conn.execute("""
                INSERT OR REPLACE INTO document_embeddings
                (document_id, embedding, model_id, dimensions, chunk_count, embedded_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                document_id,
                embedding_blob,
                model_id,
                len(embedding),
                chunk_count,
                datetime.now().isoformat(),
            ))
    
    def get_document_embedding(self, document_id: str) -> Optional[List[float]]:
        """
        Get document-level embedding.
        
        Args:
            document_id: Document ID
            
        Returns:
            Embedding vector or None if not found
        """
        self._check_closed()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT embedding FROM document_embeddings WHERE document_id = ?",
                (document_id,)
            )
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            return self._unpack_embedding(row["embedding"])
    
    def search_documents(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        min_score: float = 0.0,
        exclude_root_paths: Optional[List[str]] = None,
        include_under: Optional[str] = None,
        include_roots: Optional[List[str]] = None,
    ) -> List[DocumentSearchResult]:
        """
        Document-level semantic search using document embeddings.
        
        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            min_score: Minimum similarity score
            exclude_root_paths: Optional root paths whose documents to exclude
            include_under: Scoped directory for include-based filtering
            include_roots: Allowed root prefixes within include_under
            
        Returns:
            List of DocumentSearchResult
        """
        self._check_closed()
        
        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm > 0:
            query_vec = query_vec / query_norm
        
        with self._lock:
            where_clauses = []
            params: List[Any] = []
            if exclude_root_paths:
                for rp in exclude_root_paths:
                    where_clauses.append("d.file_path NOT LIKE ?")
                    params.append(rp.rstrip("/") + "/%")
            if include_under and include_roots:
                or_parts = ["d.file_path NOT LIKE ?"]
                params.append(include_under.rstrip("/") + "/%")
                for ir in include_roots:
                    or_parts.append("d.file_path LIKE ?")
                    params.append(ir.rstrip("/") + "/%")
                where_clauses.append(f"({' OR '.join(or_parts)})")
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            cursor = self._conn.execute(f"""
                SELECT d.document_id, d.file_path, d.file_type, d.metadata,
                       de.embedding, de.chunk_count
                FROM documents d
                JOIN document_embeddings de ON d.document_id = de.document_id
                {where_sql}
            """, params)
            
            results = []
            for row in cursor.fetchall():
                embedding = self._unpack_embedding(row["embedding"])
                doc_vec = np.array(embedding, dtype=np.float32)
                doc_norm = np.linalg.norm(doc_vec)
                if doc_norm > 0:
                    doc_vec = doc_vec / doc_norm
                
                # Cosine similarity
                score = float(np.dot(query_vec, doc_vec))
                
                if score >= min_score:
                    results.append(DocumentSearchResult(
                        document_id=row["document_id"],
                        file_path=Path(row["file_path"]),
                        file_type=row["file_type"],
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                        chunk_count=row["chunk_count"],
                        score=score,
                    ))
            
            # Sort by score and return top_k
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]
    
    # Utility methods
    
    def _pack_embedding(self, embedding: List[float]) -> bytes:
        """Pack embedding as binary blob."""
        return struct.pack(f"{len(embedding)}f", *embedding)
    
    def _unpack_embedding(self, blob: bytes) -> List[float]:
        """Unpack embedding from binary blob."""
        count = len(blob) // 4  # 4 bytes per float32
        return list(struct.unpack(f"{count}f", blob))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        self._check_closed()
        
        with self._lock:
            doc_count = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunk_count = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            embedding_count = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            
            return {
                "document_count": doc_count,
                "chunk_count": chunk_count,
                "embedding_count": embedding_count,
                "db_path": str(self.config.db_path),
            }
    
    def vacuum(self) -> None:
        """Optimize database."""
        self._check_closed()
        
        with self._lock:
            self._conn.execute("VACUUM")
    
    def clear(self) -> None:
        """Clear all data from store."""
        self._check_closed()
        
        with self._lock:
            self._conn.executescript("""
                DELETE FROM embeddings;
                DELETE FROM chunks;
                DELETE FROM documents;
            """)
    
    def close(self) -> None:
        """Close the store."""
        if self._closed:
            return
        
        with self._lock:
            self._closed = True
            if self._conn:
                self._conn.close()
                self._conn = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
