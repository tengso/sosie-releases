"""
Tests for indexer vector store.
"""

import pytest
from datetime import datetime
from pathlib import Path

from src.indexer.store import VectorStore
from src.indexer.config import VectorStoreConfig
from src.indexer.models import Document, Chunk, EmbeddedChunk
from src.indexer.exceptions import StoreError


class TestVectorStore:
    """Tests for VectorStore."""
    
    @pytest.fixture
    def store(self, tmp_path):
        config = VectorStoreConfig(db_path=tmp_path / "test.db")
        store = VectorStore(config)
        yield store
        store.close()
    
    @pytest.fixture
    def sample_document(self, tmp_path):
        return Document(
            file_path=tmp_path / "test.pdf",
            content="Test content",
            metadata={"title": "Test"},
            content_hash="abc123",
            parsed_at=datetime.now(),
            file_type="application/pdf",
        )
    
    @pytest.fixture
    def sample_chunks(self, tmp_path):
        doc_path = tmp_path / "test.pdf"
        chunks = []
        for i in range(3):
            chunk = Chunk(
                chunk_id=f"chunk-{i}",
                document_path=doc_path,
                content=f"Chunk content {i}",
                start_offset=i * 100,
                end_offset=(i + 1) * 100,
                chunk_index=i,
            )
            embedded = EmbeddedChunk(
                chunk=chunk,
                embedding=[0.1 * i, 0.2 * i, 0.3 * i] + [0.0] * 97,  # 100-dim embedding
                model_id="test-model",
                embedded_at=datetime.now(),
            )
            chunks.append(embedded)
        return chunks
    
    def test_create_store(self, tmp_path):
        config = VectorStoreConfig(db_path=tmp_path / "test.db")
        store = VectorStore(config)
        
        assert store is not None
        store.close()
    
    def test_add_document(self, store, sample_document):
        store.add_document(sample_document)
        
        retrieved = store.get_document(sample_document.file_path)
        assert retrieved is not None
        assert retrieved.content_hash == sample_document.content_hash
    
    def test_get_nonexistent_document(self, store, tmp_path):
        result = store.get_document(tmp_path / "nonexistent.pdf")
        assert result is None
    
    def test_document_exists(self, store, sample_document):
        assert store.document_exists(sample_document.file_path) is False
        
        store.add_document(sample_document)
        
        assert store.document_exists(sample_document.file_path) is True
    
    def test_document_exists_with_hash(self, store, sample_document):
        store.add_document(sample_document)
        
        assert store.document_exists(sample_document.file_path, "abc123") is True
        assert store.document_exists(sample_document.file_path, "wrong") is False
    
    def test_remove_document(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        chunk_count = store.remove_document(sample_document.file_path)
        
        assert chunk_count == 3
        assert store.document_exists(sample_document.file_path) is False
    
    def test_add_chunks(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        retrieved = store.get_chunks_for_document(sample_document.file_path)
        assert len(retrieved) == 3
    
    def test_chunks_ordered_by_index(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        retrieved = store.get_chunks_for_document(sample_document.file_path)
        indices = [ec.chunk.chunk_index for ec in retrieved]
        assert indices == [0, 1, 2]
    
    def test_search_returns_results(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        # Query with similar embedding
        query = [0.1, 0.2, 0.3] + [0.0] * 97
        results = store.search(query, top_k=5)
        
        assert len(results) > 0
    
    def test_search_orders_by_score(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        query = [0.2, 0.4, 0.6] + [0.0] * 97  # Most similar to chunk-2
        results = store.search(query, top_k=5)
        
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
    
    def test_search_with_min_score(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        query = [0.1, 0.2, 0.3] + [0.0] * 97
        results = store.search(query, top_k=5, min_score=0.5)
        
        for result in results:
            assert result.score >= 0.5
    
    def test_search_with_path_filter(self, store, tmp_path):
        # Add documents with different paths
        for i in range(2):
            doc_path = tmp_path / f"doc{i}.pdf"
            doc = Document(
                file_path=doc_path,
                content=f"Content {i}",
                metadata={},
                content_hash=f"hash{i}",
                parsed_at=datetime.now(),
                file_type="application/pdf",
            )
            store.add_document(doc)
            
            chunk = Chunk(
                chunk_id=f"chunk-doc{i}",
                document_path=doc_path,
                content=f"Chunk {i}",
                start_offset=0,
                end_offset=10,
                chunk_index=0,
            )
            embedded = EmbeddedChunk(
                chunk=chunk,
                embedding=[0.1] * 100,
                model_id="test",
                embedded_at=datetime.now(),
            )
            store.add_chunks([embedded])
        
        # Search with filter
        query = [0.1] * 100
        filter_path = tmp_path / "doc0.pdf"
        results = store.search(query, top_k=5, filter_paths=[filter_path])
        
        for result in results:
            assert result.document_path == filter_path
    
    def test_get_stats(self, store, sample_document, sample_chunks):
        stats = store.get_stats()
        assert stats["document_count"] == 0
        
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        stats = store.get_stats()
        assert stats["document_count"] == 1
        assert stats["chunk_count"] == 3
        assert stats["embedding_count"] == 3
    
    def test_clear(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        
        store.clear()
        
        stats = store.get_stats()
        assert stats["document_count"] == 0
        assert stats["chunk_count"] == 0
    
    def test_context_manager(self, tmp_path):
        config = VectorStoreConfig(db_path=tmp_path / "test.db")
        
        with VectorStore(config) as store:
            assert store is not None
    
    def test_closed_store_raises(self, tmp_path):
        config = VectorStoreConfig(db_path=tmp_path / "test.db")
        store = VectorStore(config)
        store.close()
        
        with pytest.raises(StoreError, match="closed"):
            store.get_stats()
    
    def test_vacuum(self, store, sample_document, sample_chunks):
        store.add_document(sample_document)
        store.add_chunks(sample_chunks)
        store.remove_document(sample_document.file_path)
        
        # Should not raise
        store.vacuum()
    
    def test_update_document(self, store, tmp_path):
        doc_path = tmp_path / "test.pdf"
        
        # Add initial document
        doc1 = Document(
            file_path=doc_path,
            content="Initial",
            metadata={},
            content_hash="hash1",
            parsed_at=datetime.now(),
            file_type="application/pdf",
        )
        store.add_document(doc1)
        
        # Update with new hash
        doc2 = Document(
            file_path=doc_path,
            content="Updated",
            metadata={},
            content_hash="hash2",
            parsed_at=datetime.now(),
            file_type="application/pdf",
        )
        store.add_document(doc2)
        
        # Should have updated hash
        retrieved = store.get_document(doc_path)
        assert retrieved.content_hash == "hash2"
