"""
Indexer package for document parsing, chunking, and embedding.

This package consumes file events from the watcher and maintains
a searchable index of document chunks with embeddings.
"""

from .models import (
    Document,
    Chunk,
    EmbeddedChunk,
    SearchResult,
    DocumentSearchResult,
    IndexerEvent,
    IndexerEventType,
    compute_content_hash,
    compute_file_hash,
)

from .config import (
    IndexerConfig,
    ChunkingConfig,
    EmbeddingConfig,
    VectorStoreConfig,
)

from .exceptions import (
    IndexerError,
    ParseError,
    UnsupportedFileTypeError,
    ChunkingError,
    EmbeddingError,
    EmbeddingAPIError,
    EmbeddingRateLimitError,
    EmbeddingAuthError,
    StoreError,
    DocumentNotFoundError,
    IndexerProcessError,
)

from .parsers import (
    BaseParser,
    ParserRegistry,
    PDFParser,
    TextParser,
    create_default_registry,
)

from .chunker import Chunker

from .embeddings import (
    BaseEmbedder,
    OpenAIEmbedder,
    create_embedder,
)

from .store import VectorStore

from .process import IndexerProcess


__all__ = [
    # Models
    "Document",
    "Chunk",
    "EmbeddedChunk",
    "SearchResult",
    "DocumentSearchResult",
    "IndexerEvent",
    "IndexerEventType",
    "compute_content_hash",
    "compute_file_hash",
    
    # Config
    "IndexerConfig",
    "ChunkingConfig",
    "EmbeddingConfig",
    "VectorStoreConfig",
    
    # Exceptions
    "IndexerError",
    "ParseError",
    "UnsupportedFileTypeError",
    "ChunkingError",
    "EmbeddingError",
    "EmbeddingAPIError",
    "EmbeddingRateLimitError",
    "EmbeddingAuthError",
    "StoreError",
    "DocumentNotFoundError",
    "IndexerProcessError",
    
    # Parsers
    "BaseParser",
    "ParserRegistry",
    "PDFParser",
    "TextParser",
    "create_default_registry",
    
    # Chunker
    "Chunker",
    
    # Embeddings
    "BaseEmbedder",
    "OpenAIEmbedder",
    "create_embedder",
    
    # Store
    "VectorStore",
    
    # Process
    "IndexerProcess",
]
