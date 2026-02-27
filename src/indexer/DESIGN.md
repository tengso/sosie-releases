# Indexer Package Design

## Overview

The indexer package consumes file change events from the watcher and maintains a searchable index of document chunks with embeddings. It supports LLM-based Q&A and deep research agents by providing semantic search capabilities over watched documents.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           IndexerProcess                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ EventConsumer│→ │   Parser     │→ │   Chunker    │→ │  Embedder   │  │
│  │              │  │   Registry   │  │              │  │  (Pluggable)│  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘  │
│         ↑                                                      ↓         │
│         │                                              ┌─────────────┐  │
│  ┌──────────────┐                                      │   Vector    │  │
│  │ Watcher Queue│                                      │   Store     │  │
│  │ (file events)│                                      │  (SQLite)   │  │
│  └──────────────┘                                      └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Models (`models.py`)

```python
@dataclass
class Document:
    """Represents a parsed document."""
    file_path: Path           # Absolute path to source file
    content: str              # Full text content
    metadata: Dict[str, Any]  # File metadata (title, author, pages, etc.)
    content_hash: str         # SHA-256 of file content
    parsed_at: datetime       # When document was parsed
    file_type: str            # MIME type or extension

@dataclass
class Chunk:
    """A chunk of document content for embedding."""
    chunk_id: str             # Unique ID (UUID)
    document_path: Path       # Source document path
    content: str              # Chunk text content
    start_offset: int         # Character offset in original document
    end_offset: int           # End character offset
    chunk_index: int          # Sequential chunk number in document
    metadata: Dict[str, Any]  # Inherited + chunk-specific metadata
    
@dataclass
class EmbeddedChunk:
    """A chunk with its embedding vector."""
    chunk: Chunk
    embedding: List[float]    # Embedding vector
    model_id: str             # Which embedding model was used
    embedded_at: datetime     # When embedding was generated

@dataclass
class SearchResult:
    """Result from semantic search."""
    chunk: Chunk
    score: float              # Similarity score (0-1)
    document_path: Path
    highlights: List[str]     # Relevant text snippets

@dataclass
class DocumentSearchResult:
    """Result from document-level semantic search."""
    document_id: str
    file_path: Path
    file_type: str
    metadata: Dict[str, Any]
    chunk_count: int
    score: float
```

### 2. Parser Registry (`parsers/`)

Pluggable document parsers with a registry pattern.

```python
class BaseParser(ABC):
    """Abstract base class for document parsers."""
    
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions."""
        pass
    
    @abstractmethod
    def supported_mimetypes(self) -> List[str]:
        """Return list of supported MIME types."""
        pass
    
    @abstractmethod
    def parse(self, file_path: Path) -> Document:
        """Parse file and return Document."""
        pass
    
    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the file."""
        pass

class ParserRegistry:
    """Registry for document parsers."""
    
    def register(self, parser: BaseParser) -> None:
        """Register a parser."""
        
    def get_parser(self, file_path: Path) -> Optional[BaseParser]:
        """Get appropriate parser for file."""
        
    def parse(self, file_path: Path) -> Document:
        """Parse file using appropriate parser."""
```

**Initial Parsers:**

| Parser | Extensions | Library |
|--------|------------|---------|
| `PDFParser` | `.pdf` | `pypdf` or `pdfplumber` |
| `TextParser` | `.txt`, `.md`, `.rst` | Built-in |
| `CodeParser` | `.py`, `.js`, `.ts`, etc. | Built-in with syntax awareness |

### 3. Chunker (`chunker.py`)

Splits documents into semantically meaningful chunks.

```python
@dataclass
class ChunkingConfig:
    """Configuration for chunking."""
    chunk_size: int = 1000        # Target chunk size in characters
    chunk_overlap: int = 200      # Overlap between chunks
    min_chunk_size: int = 100     # Minimum chunk size
    max_chunk_size: int = 2000    # Maximum chunk size
    split_by: str = "sentence"    # "sentence", "paragraph", "token"
    respect_boundaries: bool = True  # Respect section/paragraph boundaries

class Chunker:
    """Splits documents into chunks."""
    
    def __init__(self, config: ChunkingConfig):
        self.config = config
    
    def chunk(self, document: Document) -> List[Chunk]:
        """Split document into chunks."""
        
    def chunk_by_sentences(self, text: str) -> List[str]:
        """Split text by sentence boundaries."""
        
    def chunk_by_paragraphs(self, text: str) -> List[str]:
        """Split text by paragraph boundaries."""
        
    def merge_small_chunks(self, chunks: List[str]) -> List[str]:
        """Merge chunks that are too small."""
```

**Chunking Strategy:**

1. First split by major boundaries (sections, headings)
2. Within sections, split by paragraphs
3. If paragraphs exceed max size, split by sentences
4. Apply overlap for context continuity
5. Merge small chunks with neighbors

### 4. Embedding Provider (`embeddings/`)

Pluggable embedding providers.

```python
@dataclass
class EmbeddingConfig:
    """Configuration for embedding provider."""
    model_id: str                    # Model identifier
    dimensions: int                  # Embedding dimensions
    batch_size: int = 100            # Batch size for API calls
    max_retries: int = 3             # Retry count on failure
    timeout_seconds: float = 30.0    # Request timeout

class BaseEmbedder(ABC):
    """Abstract base class for embedding providers."""
    
    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts."""
        pass
    
    @abstractmethod
    def embed_single(self, text: str) -> List[float]:
        """Generate embedding for single text."""
        pass
    
    @property
    @abstractmethod
    def model_id(self) -> str:
        """Return model identifier."""
        pass
    
    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return embedding dimensions."""
        pass

class OpenAIEmbedder(BaseEmbedder):
    """OpenAI embedding provider."""
    
    # Environment variables:
    # - OPENAI_API_KEY: API key (required)
    # - OPENAI_API_BASE: Base URL (optional, for proxies)
    # - OPENAI_HTTP_PROXY: HTTP proxy URL (optional)
    # - OPENAI_HTTPS_PROXY: HTTPS proxy URL (optional)
    
    def __init__(
        self,
        model: str = "text-embedding-3-large",
        dimensions: int = 3072,
        api_key: Optional[str] = None,      # Falls back to env var
        api_base: Optional[str] = None,     # Falls back to env var
        http_proxy: Optional[str] = None,   # Falls back to env var
    ):
        pass
```

**Supported Models:**

| Provider | Model | Dimensions | Notes |
|----------|-------|------------|-------|
| OpenAI | `text-embedding-3-large` | 3072 | Default, best quality |
| OpenAI | `text-embedding-3-small` | 1536 | Faster, cheaper |
| OpenAI | `text-embedding-ada-002` | 1536 | Legacy |

### 5. Vector Store (`store.py`)

SQLite-based vector storage with similarity search.

```python
@dataclass 
class VectorStoreConfig:
    """Configuration for vector store."""
    db_path: Path                    # SQLite database path
    embedding_dimensions: int        # Embedding vector size
    use_approximate_search: bool = False  # Use ANN index
    similarity_metric: str = "cosine"     # "cosine", "l2", "dot"

class VectorStore:
    """SQLite-based vector storage."""
    
    def __init__(self, config: VectorStoreConfig):
        pass
    
    # Document operations
    def add_document(self, document: Document) -> None:
        """Add document metadata."""
        
    def remove_document(self, file_path: Path) -> int:
        """Remove document and all its chunks. Returns chunk count."""
        
    def get_document(self, file_path: Path) -> Optional[Document]:
        """Get document by path."""
        
    def document_exists(self, file_path: Path, content_hash: str) -> bool:
        """Check if document with same hash exists."""
    
    # Chunk operations
    def add_chunks(self, chunks: List[EmbeddedChunk]) -> None:
        """Add embedded chunks."""
        
    def get_chunks_for_document(self, file_path: Path) -> List[EmbeddedChunk]:
        """Get all chunks for a document."""
    
    # Search operations
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter_paths: Optional[List[Path]] = None,
        min_score: float = 0.0,
    ) -> List[SearchResult]:
        """Semantic search over chunks."""
        
    def search_documents(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> List[DocumentSearchResult]:
        """Document-level semantic search."""
    
    # Planned (not yet implemented):
    # def hybrid_search(
    #     self,
    #     query_embedding: List[float],
    #     query_text: str,
    #     top_k: int = 10,
    #     alpha: float = 0.5,
    # ) -> List[SearchResult]:
    #     """Hybrid semantic + keyword search."""
    
    # Maintenance
    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        
    def vacuum(self) -> None:
        """Optimize database."""
```

**Database Schema:**

```sql
-- Documents table
CREATE TABLE documents (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    file_type TEXT NOT NULL,
    metadata JSON,
    parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chunks table
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL REFERENCES documents(file_path) ON DELETE CASCADE,
    content TEXT NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Embeddings table (separate for flexibility)
CREATE TABLE embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,          -- Packed float32 array
    model_id TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    embedded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search index
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='rowid'
);

-- Indexes
CREATE INDEX idx_chunks_file_path ON chunks(file_path);
CREATE INDEX idx_embeddings_model ON embeddings(model_id);
```

### 6. Indexer Process (`process.py`)

Main orchestrator that ties everything together.

```python
@dataclass
class IndexerConfig:
    """Configuration for indexer process."""
    # Watcher integration
    watcher_db_path: Path            # Watcher's SQLite database
    
    # Vector store
    vector_db_path: Path             # Vector store database path
    
    # Parsing
    supported_extensions: List[str] = field(default_factory=lambda: ['.pdf', '.txt', '.md'])
    
    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 200
    
    # Embedding
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    embedding_batch_size: int = 100
    
    # Processing
    max_concurrent_files: int = 4
    retry_failed_after_seconds: int = 300
    
    # OpenAI configuration (can also use env vars)
    openai_api_key: Optional[str] = None
    openai_api_base: Optional[str] = None
    openai_http_proxy: Optional[str] = None

class IndexerProcess:
    """Main indexer process."""
    
    def __init__(self, config: IndexerConfig):
        self.config = config
        self.parser_registry = ParserRegistry()
        self.chunker = Chunker(ChunkingConfig(...))
        self.embedder = self._create_embedder()
        self.store = VectorStore(VectorStoreConfig(...))
        self.watcher = WatcherProcess(WatcherConfig(db_path=config.watcher_db_path))
    
    def start(self) -> None:
        """Start the indexer process."""
        
    def stop(self) -> None:
        """Stop the indexer process."""
        
    def process_event(self, event: FileEvent) -> None:
        """Process a single file event."""
        
    def _handle_add_or_update(self, event: FileEvent) -> None:
        """Handle file add or update."""
        # 1. Check if file type is supported
        # 2. Parse document
        # 3. Check content hash - skip if unchanged
        # 4. Remove old chunks if update
        # 5. Chunk document
        # 6. Generate embeddings
        # 7. Store in vector store
        
    def _handle_delete(self, event: FileEvent) -> None:
        """Handle file deletion."""
        # 1. Remove document from store
        # 2. Cascades to remove chunks and embeddings
        
    def _handle_move(self, event: FileEvent) -> None:
        """Handle file move."""
        # 1. Update file path in store
        # 2. Keep chunks and embeddings
    
    # Root management (delegated to RootManager)
    roots: RootManager
    
    def add_root(self, root: Path) -> bool: ...
    def remove_root(self, root: Path) -> None: ...
    def get_roots(self) -> List[Path]: ...
    def resync(self) -> None: ...
    def integrity_check(self) -> None: ...
    def build_integrity_report(self) -> Dict[str, Any]: ...
    
    # Search API
    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_paths: Optional[List[Path]] = None,
    ) -> List[SearchResult]:
        """Semantic search over chunks."""
    
    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        filter_paths: Optional[List[Path]] = None,
    ) -> List[SearchResult]:
        """Full-text keyword search using BM25."""
    
    def search_documents(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[DocumentSearchResult]:
        """Document-level semantic search."""
    
    def get_context_for_query(
        self,
        query: str,
        max_chunks: int = 5,
        max_chars: int = 8000,
    ) -> str:
        """Get formatted context for LLM query."""
```

## Event Processing Flow

```
FileEvent (from Watcher)
         │
         ▼
    ┌─────────┐
    │ Filter  │──── Unsupported type ──→ Skip
    └────┬────┘
         │ Supported
         ▼
    ┌─────────┐
    │  Parse  │──── Parse error ──→ Log & retry later
    └────┬────┘
         │ Success
         ▼
    ┌─────────┐
    │  Hash   │──── Same hash ──→ Skip (no change)
    │  Check  │
    └────┬────┘
         │ Changed
         ▼
    ┌─────────┐
    │  Chunk  │
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  Embed  │──── API error ──→ Retry with backoff
    └────┬────┘
         │ Success
         ▼
    ┌─────────┐
    │  Store  │
    └─────────┘
```

## Error Handling

| Error Type | Handling Strategy |
|------------|-------------------|
| Parse failure | Log error, add to retry queue |
| Embedding API timeout | Retry with exponential backoff |
| Embedding API rate limit | Queue and batch, respect rate limits |
| Embedding API key invalid | Fail fast, log clear error |
| Database error | Retry, then fail with clear error |
| File not found (during processing) | Treat as delete event |

## Configuration via Environment Variables

```bash
# OpenAI API
OPENAI_API_KEY=sk-...              # Required for OpenAI embeddings
OPENAI_API_BASE=https://...        # Optional: custom API endpoint
OPENAI_HTTP_PROXY=http://...       # Optional: HTTP proxy
OPENAI_HTTPS_PROXY=https://...     # Optional: HTTPS proxy

# Indexer settings (optional overrides)
INDEXER_CHUNK_SIZE=1000
INDEXER_CHUNK_OVERLAP=200
INDEXER_EMBEDDING_MODEL=text-embedding-3-large
INDEXER_EMBEDDING_BATCH_SIZE=100
```

## File Structure

```
src/indexer/
├── __init__.py           # Public API exports
├── DESIGN.md             # This document
├── models.py             # Data models (Document, Chunk, SearchResult, DocumentSearchResult, etc.)
├── config.py             # Configuration
├── exceptions.py         # Custom exceptions
├── activity.py           # ActivityLogger + DatabaseLogHandler
├── roots.py              # RootManager (add/remove/scan roots, resync, integrity)
├── chunker.py            # Document chunking
├── store.py              # Vector store
├── process.py            # Main indexer process (orchestration + search API)
├── api_server.py         # HTTP REST API (delegates to IndexerProcess)
├── parsers/
│   ├── __init__.py       # Parser registry
│   ├── base.py           # Base parser class
│   ├── pdf.py            # PDF parser
│   ├── text.py           # Plain text parser
│   └── word.py           # Word document parser
└── embeddings/
    ├── __init__.py       # Embedder factory
    ├── base.py           # Base embedder class
    └── openai.py         # OpenAI embedder
```

## Public API

```python
from indexer import (
    # Main process
    IndexerProcess,
    IndexerConfig,
    
    # Models
    Document,
    Chunk,
    EmbeddedChunk,
    SearchResult,
    DocumentSearchResult,
    
    # Parsers (for extension)
    BaseParser,
    ParserRegistry,
    
    # Embedders (for extension)
    BaseEmbedder,
    OpenAIEmbedder,
    
    # Store
    VectorStore,
    VectorStoreConfig,
)

# Example usage
config = IndexerConfig(
    watcher_db_path=Path("watcher.db"),
    vector_db_path=Path("vectors.db"),
)

with IndexerProcess(config) as indexer:
    indexer.start()
    
    # Search
    results = indexer.search("How to configure authentication?")
    for result in results:
        print(f"{result.document_path}: {result.score:.2f}")
        print(f"  {result.chunk.content[:200]}...")
    
    # Get context for LLM
    context = indexer.get_context_for_query(
        "What are the main features?",
        max_chunks=5,
    )
    print(context)
```

## Dependencies

```
pypdf>=3.0.0              # PDF parsing
tiktoken>=0.5.0           # Token counting for OpenAI
openai>=1.0.0             # OpenAI API client
httpx>=0.25.0             # HTTP client with proxy support
numpy>=1.24.0             # Vector operations
```

## Future Extensions

1. **Additional Parsers:**
   - DOCX (python-docx)
   - HTML (BeautifulSoup)
   - EPUB
   - Images with OCR (pytesseract)

2. **Additional Embedders:**
   - Local models (sentence-transformers)
   - Cohere
   - Anthropic (when available)
   - Azure OpenAI

3. **Advanced Features:**
   - Hybrid search (semantic + keyword, `hybrid_search()`)
   - Incremental re-indexing
   - Metadata extraction and filtering
   - Multi-modal embeddings (images)
   - Clustering and summarization
   - Index versioning and migration
   - ANN search via sqlite-vec
