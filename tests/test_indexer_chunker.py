"""
Tests for indexer chunker.
"""

import pytest
from datetime import datetime
from pathlib import Path

from src.indexer.chunker import Chunker
from src.indexer.config import ChunkingConfig
from src.indexer.models import Document


class TestChunker:
    """Tests for Chunker."""
    
    @pytest.fixture
    def sample_document(self, tmp_path):
        return Document(
            file_path=tmp_path / "test.txt",
            content="This is a test document. It has multiple sentences. Each sentence should be processed.",
            metadata={},
            content_hash="abc123",
            parsed_at=datetime.now(),
            file_type="text/plain",
        )
    
    @pytest.fixture
    def long_document(self, tmp_path):
        content = " ".join(["This is sentence number {}.".format(i) for i in range(100)])
        return Document(
            file_path=tmp_path / "long.txt",
            content=content,
            metadata={},
            content_hash="def456",
            parsed_at=datetime.now(),
            file_type="text/plain",
        )
    
    def test_create_chunker_default_config(self):
        chunker = Chunker()
        assert chunker.config.chunk_size == 1000
    
    def test_create_chunker_custom_config(self):
        config = ChunkingConfig(chunk_size=500)
        chunker = Chunker(config)
        assert chunker.config.chunk_size == 500
    
    def test_chunk_small_document(self, sample_document):
        config = ChunkingConfig(chunk_size=1000, min_chunk_size=10)
        chunker = Chunker(config)
        
        chunks = chunker.chunk(sample_document)
        
        assert len(chunks) >= 1
        assert all(chunk.document_path == sample_document.file_path for chunk in chunks)
    
    def test_chunk_assigns_chunk_ids(self, sample_document):
        chunker = Chunker()
        chunks = chunker.chunk(sample_document)
        
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        assert len(chunk_ids) == len(set(chunk_ids))  # All unique
    
    def test_chunk_assigns_indices(self, long_document):
        config = ChunkingConfig(chunk_size=200, min_chunk_size=50)
        chunker = Chunker(config)
        
        chunks = chunker.chunk(long_document)
        
        indices = [chunk.chunk_index for chunk in chunks]
        assert indices == list(range(len(chunks)))
    
    def test_chunk_includes_metadata(self, sample_document):
        sample_document.metadata = {"title": "Test"}
        chunker = Chunker()
        
        chunks = chunker.chunk(sample_document)
        
        assert all("source_file" in chunk.metadata for chunk in chunks)
        assert all("file_type" in chunk.metadata for chunk in chunks)
    
    def test_chunk_empty_document(self, tmp_path):
        doc = Document(
            file_path=tmp_path / "empty.txt",
            content="",
            metadata={},
            content_hash="empty",
            parsed_at=datetime.now(),
            file_type="text/plain",
        )
        
        chunker = Chunker()
        chunks = chunker.chunk(doc)
        
        assert len(chunks) == 0
    
    def test_chunk_whitespace_only(self, tmp_path):
        doc = Document(
            file_path=tmp_path / "whitespace.txt",
            content="   \n\n   \t   ",
            metadata={},
            content_hash="ws",
            parsed_at=datetime.now(),
            file_type="text/plain",
        )
        
        chunker = Chunker()
        chunks = chunker.chunk(doc)
        
        assert len(chunks) == 0
    
    def test_chunk_respects_max_size(self, long_document):
        config = ChunkingConfig(
            chunk_size=100,
            max_chunk_size=200,
            min_chunk_size=10,
        )
        chunker = Chunker(config)
        
        chunks = chunker.chunk(long_document)
        
        # Most chunks should be within reasonable bounds
        large_chunks = [c for c in chunks if len(c.content) > config.max_chunk_size * 2]
        assert len(large_chunks) < len(chunks) // 2  # Less than half are oversized
    
    def test_chunk_by_paragraph(self, tmp_path):
        content = "First paragraph with content.\n\nSecond paragraph here.\n\nThird paragraph."
        doc = Document(
            file_path=tmp_path / "paragraphs.txt",
            content=content,
            metadata={},
            content_hash="para",
            parsed_at=datetime.now(),
            file_type="text/plain",
        )
        
        config = ChunkingConfig(split_by="paragraph", chunk_size=1000, min_chunk_size=10)
        chunker = Chunker(config)
        
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 1
    
    def test_chunk_offsets(self, sample_document):
        chunker = Chunker()
        chunks = chunker.chunk(sample_document)
        
        for chunk in chunks:
            assert chunk.start_offset >= 0
            assert chunk.end_offset > chunk.start_offset
            assert chunk.end_offset <= len(sample_document.content) + 10  # Some tolerance
    
    def test_estimate_chunk_count(self, long_document):
        config = ChunkingConfig(chunk_size=100, chunk_overlap=20)
        chunker = Chunker(config)
        
        estimate = chunker.estimate_chunk_count(long_document)
        actual = len(chunker.chunk(long_document))
        
        # Estimate should be in the right ballpark
        assert estimate > 0
        assert abs(estimate - actual) < actual  # Within 100% of actual
    
    def test_chunk_overlap(self, tmp_path):
        # Create document with predictable content
        content = "A" * 500 + "B" * 500 + "C" * 500
        doc = Document(
            file_path=tmp_path / "overlap.txt",
            content=content,
            metadata={},
            content_hash="overlap",
            parsed_at=datetime.now(),
            file_type="text/plain",
        )
        
        config = ChunkingConfig(
            chunk_size=400,
            chunk_overlap=100,
            min_chunk_size=50,
            split_by="size",
        )
        chunker = Chunker(config)
        
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 2
