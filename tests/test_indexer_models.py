"""
Tests for indexer models.
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile

from src.indexer.models import (
    Document,
    Chunk,
    EmbeddedChunk,
    SearchResult,
    IndexerEvent,
    IndexerEventType,
    compute_content_hash,
    compute_file_hash,
)


class TestDocument:
    """Tests for Document model."""
    
    def test_create_document(self, tmp_path):
        doc = Document(
            file_path=tmp_path / "test.pdf",
            content="Test content",
            metadata={"title": "Test"},
            content_hash="abc123",
            parsed_at=datetime.now(),
            file_type="application/pdf",
        )
        
        assert doc.file_path == tmp_path / "test.pdf"
        assert doc.content == "Test content"
        assert doc.metadata["title"] == "Test"
        assert doc.content_hash == "abc123"
        assert doc.file_type == "application/pdf"
    
    def test_document_requires_absolute_path(self):
        with pytest.raises(ValueError, match="absolute"):
            Document(
                file_path=Path("relative/path.pdf"),
                content="Test",
                metadata={},
                content_hash="abc",
                parsed_at=datetime.now(),
                file_type="application/pdf",
            )
    
    def test_document_serialization(self, tmp_path):
        now = datetime.now()
        doc = Document(
            file_path=tmp_path / "test.pdf",
            content="Test content",
            metadata={"title": "Test"},
            content_hash="abc123",
            parsed_at=now,
            file_type="application/pdf",
        )
        
        data = doc.to_dict()
        restored = Document.from_dict(data)
        
        assert restored.file_path == doc.file_path
        assert restored.content == doc.content
        assert restored.metadata == doc.metadata
        assert restored.content_hash == doc.content_hash
        assert restored.file_type == doc.file_type
    
    def test_document_string_path_conversion(self, tmp_path):
        doc = Document(
            file_path=str(tmp_path / "test.pdf"),
            content="Test",
            metadata={},
            content_hash="abc",
            parsed_at=datetime.now(),
            file_type="application/pdf",
        )
        
        assert isinstance(doc.file_path, Path)


class TestChunk:
    """Tests for Chunk model."""
    
    def test_create_chunk(self, tmp_path):
        chunk = Chunk(
            chunk_id="chunk-1",
            document_path=tmp_path / "test.pdf",
            content="Chunk content",
            start_offset=0,
            end_offset=13,
            chunk_index=0,
        )
        
        assert chunk.chunk_id == "chunk-1"
        assert chunk.content == "Chunk content"
        assert chunk.start_offset == 0
        assert chunk.end_offset == 13
        assert chunk.chunk_index == 0
    
    def test_chunk_auto_generates_id(self, tmp_path):
        chunk = Chunk(
            chunk_id="",
            document_path=tmp_path / "test.pdf",
            content="Content",
            start_offset=0,
            end_offset=7,
            chunk_index=0,
        )
        
        assert chunk.chunk_id  # Should have auto-generated UUID
    
    def test_chunk_serialization(self, tmp_path):
        chunk = Chunk(
            chunk_id="chunk-1",
            document_path=tmp_path / "test.pdf",
            content="Chunk content",
            start_offset=0,
            end_offset=13,
            chunk_index=0,
            metadata={"page": 1},
        )
        
        data = chunk.to_dict()
        restored = Chunk.from_dict(data)
        
        assert restored.chunk_id == chunk.chunk_id
        assert restored.content == chunk.content
        assert restored.metadata == chunk.metadata


class TestEmbeddedChunk:
    """Tests for EmbeddedChunk model."""
    
    def test_create_embedded_chunk(self, tmp_path):
        chunk = Chunk(
            chunk_id="chunk-1",
            document_path=tmp_path / "test.pdf",
            content="Content",
            start_offset=0,
            end_offset=7,
            chunk_index=0,
        )
        
        embedded = EmbeddedChunk(
            chunk=chunk,
            embedding=[0.1, 0.2, 0.3],
            model_id="text-embedding-3-large",
            embedded_at=datetime.now(),
        )
        
        assert embedded.chunk == chunk
        assert embedded.embedding == [0.1, 0.2, 0.3]
        assert embedded.model_id == "text-embedding-3-large"
    
    def test_embedded_chunk_serialization(self, tmp_path):
        chunk = Chunk(
            chunk_id="chunk-1",
            document_path=tmp_path / "test.pdf",
            content="Content",
            start_offset=0,
            end_offset=7,
            chunk_index=0,
        )
        
        now = datetime.now()
        embedded = EmbeddedChunk(
            chunk=chunk,
            embedding=[0.1, 0.2, 0.3],
            model_id="test-model",
            embedded_at=now,
        )
        
        data = embedded.to_dict()
        restored = EmbeddedChunk.from_dict(data)
        
        assert restored.chunk.chunk_id == embedded.chunk.chunk_id
        assert restored.embedding == embedded.embedding
        assert restored.model_id == embedded.model_id


class TestSearchResult:
    """Tests for SearchResult model."""
    
    def test_create_search_result(self, tmp_path):
        chunk = Chunk(
            chunk_id="chunk-1",
            document_path=tmp_path / "test.pdf",
            content="Content",
            start_offset=0,
            end_offset=7,
            chunk_index=0,
        )
        
        result = SearchResult(
            chunk=chunk,
            score=0.95,
            document_path=tmp_path / "test.pdf",
            highlights=["Content"],
        )
        
        assert result.score == 0.95
        assert result.highlights == ["Content"]
    
    def test_search_result_serialization(self, tmp_path):
        chunk = Chunk(
            chunk_id="chunk-1",
            document_path=tmp_path / "test.pdf",
            content="Content",
            start_offset=0,
            end_offset=7,
            chunk_index=0,
        )
        
        result = SearchResult(
            chunk=chunk,
            score=0.95,
            document_path=tmp_path / "test.pdf",
        )
        
        data = result.to_dict()
        assert data["score"] == 0.95


class TestIndexerEvent:
    """Tests for IndexerEvent model."""
    
    def test_create_indexer_event(self, tmp_path):
        event = IndexerEvent(
            event_type=IndexerEventType.INDEXED,
            file_path=tmp_path / "test.pdf",
            timestamp=datetime.now(),
            chunk_count=5,
        )
        
        assert event.event_type == IndexerEventType.INDEXED
        assert event.chunk_count == 5
    
    def test_indexer_event_failed(self, tmp_path):
        event = IndexerEvent(
            event_type=IndexerEventType.FAILED,
            file_path=tmp_path / "test.pdf",
            timestamp=datetime.now(),
            error_message="Parse error",
        )
        
        assert event.event_type == IndexerEventType.FAILED
        assert event.error_message == "Parse error"
    
    def test_indexer_event_serialization(self, tmp_path):
        now = datetime.now()
        event = IndexerEvent(
            event_type=IndexerEventType.INDEXED,
            file_path=tmp_path / "test.pdf",
            timestamp=now,
            chunk_count=5,
        )
        
        data = event.to_dict()
        restored = IndexerEvent.from_dict(data)
        
        assert restored.event_type == event.event_type
        assert restored.chunk_count == event.chunk_count


class TestHashFunctions:
    """Tests for hash utility functions."""
    
    def test_compute_content_hash(self):
        content = b"Hello, World!"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest
    
    def test_compute_content_hash_different_content(self):
        hash1 = compute_content_hash(b"Hello")
        hash2 = compute_content_hash(b"World")
        
        assert hash1 != hash2
    
    def test_compute_file_hash(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")
        
        hash1 = compute_file_hash(test_file)
        hash2 = compute_file_hash(test_file)
        
        assert hash1 == hash2
        assert len(hash1) == 64
    
    def test_compute_file_hash_different_files(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")
        
        hash1 = compute_file_hash(file1)
        hash2 = compute_file_hash(file2)
        
        assert hash1 != hash2
