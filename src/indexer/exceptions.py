"""
Custom exceptions for the indexer package.
"""


class IndexerError(Exception):
    """Base exception for indexer errors."""
    pass


class ParseError(IndexerError):
    """Error during document parsing."""
    pass


class UnsupportedFileTypeError(ParseError):
    """File type is not supported."""
    pass


class ChunkingError(IndexerError):
    """Error during document chunking."""
    pass


class EmbeddingError(IndexerError):
    """Error during embedding generation."""
    pass


class EmbeddingAPIError(EmbeddingError):
    """Error from embedding API."""
    def __init__(self, message: str, status_code: int = None, retry_after: float = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class EmbeddingRateLimitError(EmbeddingAPIError):
    """Rate limit exceeded."""
    pass


class EmbeddingAuthError(EmbeddingAPIError):
    """Authentication error."""
    pass


class StoreError(IndexerError):
    """Error in vector store operations."""
    pass


class DocumentNotFoundError(StoreError):
    """Document not found in store."""
    pass


class IndexerProcessError(IndexerError):
    """Error in indexer process."""
    pass


class RootOverlapError(IndexerError):
    """New root overlaps with an existing root (parent or child)."""
    def __init__(self, message: str, existing_root: str, new_root: str, relationship: str):
        super().__init__(message)
        self.existing_root = existing_root
        self.new_root = new_root
        self.relationship = relationship  # "parent" or "child"
