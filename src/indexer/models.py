"""
Data models for the indexer package.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
import json
import uuid


class IndexerEventType(Enum):
    """Types of indexer events."""
    INDEXED = "indexed"
    REMOVED = "removed"
    UPDATED = "updated"
    FAILED = "failed"


def generate_document_id(file_path: Path) -> str:
    """
    Generate a stable document ID from file path.
    
    Args:
        file_path: Absolute path to document
        
    Returns:
        Document ID (hash of path)
    """
    return hashlib.sha256(str(file_path).encode()).hexdigest()[:16]


@dataclass
class Document:
    """Represents a parsed document."""
    file_path: Path
    content: str
    metadata: Dict[str, Any]
    content_hash: str
    parsed_at: datetime
    file_type: str
    document_id: str = field(default="")
    
    def __post_init__(self):
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
        if not self.file_path.is_absolute():
            raise ValueError(f"file_path must be absolute: {self.file_path}")
        if isinstance(self.parsed_at, str):
            self.parsed_at = datetime.fromisoformat(self.parsed_at)
        # Generate document_id if not provided
        if not self.document_id:
            self.document_id = generate_document_id(self.file_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "document_id": self.document_id,
            "file_path": str(self.file_path),
            "content": self.content,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "parsed_at": self.parsed_at.isoformat(),
            "file_type": self.file_type,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        """Deserialize from dictionary."""
        return cls(
            file_path=Path(data["file_path"]),
            content=data["content"],
            metadata=data["metadata"],
            content_hash=data["content_hash"],
            parsed_at=datetime.fromisoformat(data["parsed_at"]),
            file_type=data["file_type"],
            document_id=data.get("document_id", ""),
        )


@dataclass
class Chunk:
    """A chunk of document content for embedding."""
    chunk_id: str
    document_path: Path
    content: str
    start_offset: int
    end_offset: int
    chunk_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    document_id: str = field(default="")
    
    def __post_init__(self):
        if isinstance(self.document_path, str):
            self.document_path = Path(self.document_path)
        if not self.chunk_id:
            self.chunk_id = str(uuid.uuid4())
        if not self.document_id:
            self.document_id = generate_document_id(self.document_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_path": str(self.document_path),
            "content": self.content,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        """Deserialize from dictionary."""
        return cls(
            chunk_id=data["chunk_id"],
            document_path=Path(data["document_path"]),
            content=data["content"],
            start_offset=data["start_offset"],
            end_offset=data["end_offset"],
            chunk_index=data["chunk_index"],
            metadata=data.get("metadata", {}),
            document_id=data.get("document_id", ""),
        )


@dataclass
class EmbeddedChunk:
    """A chunk with its embedding vector."""
    chunk: Chunk
    embedding: List[float]
    model_id: str
    embedded_at: datetime
    
    def __post_init__(self):
        if isinstance(self.embedded_at, str):
            self.embedded_at = datetime.fromisoformat(self.embedded_at)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "chunk": self.chunk.to_dict(),
            "embedding": self.embedding,
            "model_id": self.model_id,
            "embedded_at": self.embedded_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmbeddedChunk":
        """Deserialize from dictionary."""
        return cls(
            chunk=Chunk.from_dict(data["chunk"]),
            embedding=data["embedding"],
            model_id=data["model_id"],
            embedded_at=datetime.fromisoformat(data["embedded_at"]),
        )


@dataclass
class SearchResult:
    """Result from semantic search."""
    chunk: Chunk
    score: float
    document_path: Path
    highlights: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if isinstance(self.document_path, str):
            self.document_path = Path(self.document_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "chunk": self.chunk.to_dict(),
            "score": self.score,
            "document_path": str(self.document_path),
            "highlights": self.highlights,
        }


@dataclass
class DocumentSearchResult:
    """Result from document-level semantic search."""
    document_id: str
    file_path: Path
    file_type: str
    metadata: Dict[str, Any]
    chunk_count: int
    score: float
    
    def __post_init__(self):
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "document_id": self.document_id,
            "file_path": str(self.file_path),
            "file_type": self.file_type,
            "metadata": self.metadata,
            "chunk_count": self.chunk_count,
            "score": self.score,
        }


@dataclass
class IndexerEvent:
    """Event emitted by the indexer."""
    event_type: IndexerEventType
    file_path: Path
    timestamp: datetime
    chunk_count: int = 0
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
        if isinstance(self.event_type, str):
            self.event_type = IndexerEventType(self.event_type)
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "event_type": self.event_type.value,
            "file_path": str(self.file_path),
            "timestamp": self.timestamp.isoformat(),
            "chunk_count": self.chunk_count,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IndexerEvent":
        """Deserialize from dictionary."""
        return cls(
            event_type=IndexerEventType(data["event_type"]),
            file_path=Path(data["file_path"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            chunk_count=data.get("chunk_count", 0),
            error_message=data.get("error_message"),
        )


def compute_content_hash(content: bytes, algorithm: str = "sha256") -> str:
    """
    Compute hash of content.
    
    Args:
        content: Content bytes to hash
        algorithm: Hash algorithm (default: sha256)
        
    Returns:
        Hex digest of hash
    """
    hasher = hashlib.new(algorithm)
    hasher.update(content)
    return hasher.hexdigest()


def compute_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    """
    Compute hash of file content.
    
    Args:
        file_path: Path to file
        algorithm: Hash algorithm (default: sha256)
        
    Returns:
        Hex digest of hash
    """
    hasher = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
