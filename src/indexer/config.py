"""
Configuration for the indexer package.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ChunkingConfig:
    """Configuration for document chunking."""
    chunk_size: int = 1000
    chunk_overlap: int = 200
    min_chunk_size: int = 100
    max_chunk_size: int = 2000
    split_by: str = "sentence"  # "sentence", "paragraph", "token"
    respect_boundaries: bool = True


@dataclass
class EmbeddingConfig:
    """Configuration for embedding provider."""
    provider: str = "openai"
    model_id: str = "text-embedding-3-large"
    dimensions: int = 3072
    batch_size: int = 100
    max_retries: int = 3
    timeout_seconds: float = 60.0
    
    # API configuration (can be overridden by env vars)
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    api_key_env: str = "OPENAI_API_KEY"
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    
    def get_api_key(self) -> Optional[str]:
        """Get API key from config or environment."""
        return self.api_key or os.environ.get(self.api_key_env) or os.environ.get("OPENAI_API_KEY")
    
    def get_api_base(self) -> Optional[str]:
        """Get API base URL from config or environment."""
        return self.api_base or os.environ.get("OPENAI_API_BASE")
    
    def get_http_proxy(self) -> Optional[str]:
        """Get HTTP proxy from config or environment."""
        return self.http_proxy or os.environ.get("HTTP_PROXY")
    
    def get_https_proxy(self) -> Optional[str]:
        """Get HTTPS proxy from config or environment."""
        return self.https_proxy or os.environ.get("HTTPS_PROXY")


@dataclass
class VectorStoreConfig:
    """Configuration for vector store."""
    db_path: Path = field(default_factory=lambda: Path("vectors.db"))
    embedding_dimensions: int = 3072
    similarity_metric: str = "cosine"  # "cosine", "l2", "dot"
    
    def __post_init__(self):
        if isinstance(self.db_path, str):
            self.db_path = Path(self.db_path)


@dataclass
class IndexerConfig:
    """Main configuration for the indexer."""
    # Watcher integration
    watcher_db_path: Path = field(default_factory=lambda: Path("watcher.db"))
    
    # Vector store
    vector_db_path: Path = field(default_factory=lambda: Path("vectors.db"))
    
    # Web frontend path (for serving React app)
    web_dist_path: Optional[Path] = None
    
    # Remote mode settings
    remote_mode: bool = False
    uploads_dir: Optional[Path] = None
    
    # Supported file types
    supported_extensions: List[str] = field(
        default_factory=lambda: [".pdf", ".txt", ".md", ".rst", ".py", ".js", ".ts"]
    )
    
    # Chunking configuration
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    
    # Embedding configuration
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    
    # Processing
    max_concurrent_files: int = 4
    retry_failed_after_seconds: int = 300
    process_interval_ms: int = 100
    
    def __post_init__(self):
        if isinstance(self.watcher_db_path, str):
            self.watcher_db_path = Path(self.watcher_db_path)
        if isinstance(self.vector_db_path, str):
            self.vector_db_path = Path(self.vector_db_path)
        if isinstance(self.chunking, dict):
            self.chunking = ChunkingConfig(**self.chunking)
        if isinstance(self.embedding, dict):
            self.embedding = EmbeddingConfig(**self.embedding)
    
    def is_supported(self, file_path: Path) -> bool:
        """Check if file type is supported."""
        if isinstance(file_path, str):
            file_path = Path(file_path)
        return file_path.suffix.lower() in self.supported_extensions
    
    def get_vector_store_config(self) -> VectorStoreConfig:
        """Get vector store configuration."""
        return VectorStoreConfig(
            db_path=self.vector_db_path,
            embedding_dimensions=self.embedding.dimensions,
        )
