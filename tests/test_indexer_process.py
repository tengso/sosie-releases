"""
Tests for indexer process.
"""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from src.indexer.process import IndexerProcess
from src.indexer.config import IndexerConfig, EmbeddingConfig, ChunkingConfig
from src.indexer.exceptions import RootOverlapError
from src.indexer.models import Document, Chunk, EmbeddedChunk, IndexerEventType
from src.indexer.parsers import ParserRegistry, TextParser
from src.indexer.embeddings.base import BaseEmbedder


class MockEmbedder(BaseEmbedder):
    """Mock embedder for testing."""
    
    def __init__(self, dimensions: int = 100):
        self._dimensions = dimensions
        self.embed_calls = []
    
    @property
    def model_id(self) -> str:
        return "mock-model"
    
    @property
    def dimensions(self) -> int:
        return self._dimensions
    
    @property
    def max_tokens(self) -> int:
        return 8191
    
    def embed(self, texts):
        self.embed_calls.append(texts)
        return [[0.1] * self._dimensions for _ in texts]


class TestIndexerProcess:
    """Tests for IndexerProcess."""
    
    @pytest.fixture
    def mock_embedder(self):
        return MockEmbedder(dimensions=100)
    
    @pytest.fixture
    def config(self, tmp_path):
        return IndexerConfig(
            watcher_db_path=tmp_path / "watcher.db",
            vector_db_path=tmp_path / "vectors.db",
            embedding=EmbeddingConfig(dimensions=100),
            chunking=ChunkingConfig(chunk_size=500, min_chunk_size=10),
        )
    
    @pytest.fixture
    def indexer(self, config, mock_embedder):
        indexer = IndexerProcess(config=config, embedder=mock_embedder)
        yield indexer
        indexer.close()
    
    def test_create_indexer(self, config, mock_embedder):
        indexer = IndexerProcess(config=config, embedder=mock_embedder)
        assert indexer is not None
        indexer.close()
    
    def test_index_text_file(self, indexer, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("This is a test document with some content for indexing.")
        
        event = indexer.index_file(test_file)
        
        assert event.event_type == IndexerEventType.INDEXED
        assert event.file_path == test_file.resolve()
        assert event.chunk_count >= 1
    
    def test_index_nonexistent_file(self, indexer, tmp_path):
        event = indexer.index_file(tmp_path / "nonexistent.txt")
        
        assert event.event_type == IndexerEventType.FAILED
        assert "not found" in event.error_message.lower()
    
    def test_index_unsupported_file(self, indexer, tmp_path):
        test_file = tmp_path / "test.xyz"
        test_file.write_text("Content")
        
        event = indexer.index_file(test_file)
        
        assert event.event_type == IndexerEventType.FAILED
    
    def test_remove_file(self, indexer, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Content for indexing")
        
        # Index first
        indexer.index_file(test_file)
        
        # Remove
        event = indexer.remove_file(test_file)
        
        assert event.event_type == IndexerEventType.REMOVED
    
    def test_skip_unchanged_file(self, indexer, tmp_path, mock_embedder):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Content that stays the same")
        
        # Index first time
        event1 = indexer.index_file(test_file)
        assert event1.chunk_count >= 1
        
        embed_count_1 = len(mock_embedder.embed_calls)
        
        # Index again - should skip
        event2 = indexer.index_file(test_file)
        
        embed_count_2 = len(mock_embedder.embed_calls)
        assert embed_count_2 == embed_count_1  # No new embed calls
    
    def test_reindex_changed_file(self, indexer, tmp_path, mock_embedder):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Original content")
        
        # Index first time
        indexer.index_file(test_file)
        embed_count_1 = len(mock_embedder.embed_calls)
        
        # Modify file
        test_file.write_text("Modified content that is different")
        
        # Index again - should reindex
        event = indexer.index_file(test_file)
        
        embed_count_2 = len(mock_embedder.embed_calls)
        assert embed_count_2 > embed_count_1
    
    def test_search(self, indexer, tmp_path, mock_embedder):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Python programming is fun and interesting.")
        
        indexer.index_file(test_file)
        
        results = indexer.search("Python programming", top_k=5)
        
        assert len(results) >= 1
    
    def test_search_empty_index(self, indexer):
        results = indexer.search("test query", top_k=5)
        assert len(results) == 0
    
    def test_get_context_for_query(self, indexer, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("This document explains how authentication works in the system.")
        
        indexer.index_file(test_file)
        
        context = indexer.get_context_for_query("authentication", max_chunks=3)
        
        assert len(context) > 0
        assert "authentication" in context.lower() or "Source:" in context
    
    def test_get_context_empty_index(self, indexer):
        context = indexer.get_context_for_query("test")
        assert context == ""
    
    def test_get_stats(self, indexer, tmp_path):
        stats = indexer.get_stats()
        
        assert "document_count" in stats
        assert "chunk_count" in stats
        assert "running" in stats
        assert stats["running"] is False
    
    def test_context_manager(self, config, mock_embedder):
        with IndexerProcess(config=config, embedder=mock_embedder) as indexer:
            assert indexer is not None
    
    def test_index_markdown_file(self, indexer, tmp_path):
        test_file = tmp_path / "readme.md"
        test_file.write_text("# Title\n\nThis is the introduction paragraph.\n\n## Section\n\nMore content here.")
        
        event = indexer.index_file(test_file)
        
        assert event.event_type == IndexerEventType.INDEXED
        assert event.chunk_count >= 1
    
    def test_index_python_file(self, indexer, tmp_path):
        test_file = tmp_path / "script.py"
        test_file.write_text("def hello():\n    '''Say hello'''\n    print('Hello, World!')")
        
        event = indexer.index_file(test_file)
        
        assert event.event_type == IndexerEventType.INDEXED
    
    def test_custom_parser_registry(self, config, mock_embedder):
        registry = ParserRegistry()
        registry.register(TextParser())
        
        indexer = IndexerProcess(
            config=config,
            parser_registry=registry,
            embedder=mock_embedder,
        )
        
        assert indexer._parser_registry is registry
        indexer.close()
    
    def test_multiple_files(self, indexer, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"doc{i}.txt"
            f.write_text(f"Document {i} content with unique text.")
            files.append(f)
        
        for f in files:
            event = indexer.index_file(f)
            assert event.event_type == IndexerEventType.INDEXED
        
        stats = indexer.get_stats()
        assert stats["document_count"] == 3
    
    def test_remove_nonexistent_file(self, indexer, tmp_path):
        event = indexer.remove_file(tmp_path / "nonexistent.txt")
        
        assert event.event_type == IndexerEventType.REMOVED
        assert event.chunk_count == 0

    def test_keyword_search_basic(self, indexer, tmp_path):
        """Test that keyword_search finds indexed content by exact words."""
        test_file = tmp_path / "policy.txt"
        test_file.write_text(
            "The company reimbursement policy allows employees to claim "
            "travel expenses up to five thousand dollars per quarter."
        )
        
        event = indexer.index_file(test_file)
        assert event.event_type == IndexerEventType.INDEXED
        
        results = indexer.keyword_search("reimbursement", top_k=5)
        
        assert len(results) >= 1, "keyword_search should find 'reimbursement'"
        assert "reimbursement" in results[0].chunk.content.lower()
        assert results[0].document_path == test_file.resolve()

    def test_keyword_search_no_match(self, indexer, tmp_path):
        """Test keyword_search returns empty when no match."""
        test_file = tmp_path / "doc.txt"
        test_file.write_text("This document is about machine learning algorithms.")
        
        indexer.index_file(test_file)
        
        results = indexer.keyword_search("reimbursement", top_k=5)
        assert len(results) == 0

    def test_keyword_search_empty_index(self, indexer):
        """Test keyword_search on empty index."""
        results = indexer.keyword_search("anything", top_k=5)
        assert len(results) == 0

    def test_keyword_search_multiple_docs(self, indexer, tmp_path):
        """Test keyword_search across multiple documents."""
        doc1 = tmp_path / "doc1.txt"
        doc1.write_text("Python programming language is versatile and powerful.")
        
        doc2 = tmp_path / "doc2.txt"
        doc2.write_text("Java programming language is used in enterprise applications.")
        
        doc3 = tmp_path / "doc3.txt"
        doc3.write_text("Cooking recipes for delicious pasta dishes.")
        
        indexer.index_file(doc1)
        indexer.index_file(doc2)
        indexer.index_file(doc3)
        
        results = indexer.keyword_search("programming", top_k=10)
        
        assert len(results) >= 2, "Should find 'programming' in at least 2 docs"
        paths = {r.document_path for r in results}
        assert doc1.resolve() in paths
        assert doc2.resolve() in paths

    def test_keyword_search_special_chars(self, indexer, tmp_path):
        """Test keyword_search handles FTS5 special characters gracefully."""
        test_file = tmp_path / "doc.txt"
        test_file.write_text("The cost-benefit analysis shows a 20% improvement in Q3-2024 results.")
        
        indexer.index_file(test_file)
        
        # These queries contain FTS5 special chars that would cause OperationalError
        # if not sanitized: hyphens, quotes, colons, asterisks
        for query in ["cost-benefit", 'Q3-2024', "20%", "cost:benefit", '"analysis"']:
            results = indexer.keyword_search(query, top_k=5)
            # Should not raise; may or may not find results depending on tokenization
            assert isinstance(results, list)

    def test_keyword_search_cjk(self, indexer, tmp_path):
        """Test keyword_search finds CJK characters via LIKE fallback."""
        test_file = tmp_path / "chinese.txt"
        test_file.write_text("由著名鋼琴家陳潔女士親自操刀精心打磨")
        
        indexer.index_file(test_file)
        
        results = indexer.keyword_search("陳潔", top_k=5)
        assert len(results) >= 1, "keyword_search should find CJK text '陳潔'"
        assert "陳潔" in results[0].chunk.content

    def test_keyword_search_with_filter(self, indexer, tmp_path):
        """Test keyword_search with path filter."""
        doc1 = tmp_path / "doc1.txt"
        doc1.write_text("Python programming language guide.")
        
        doc2 = tmp_path / "doc2.txt"
        doc2.write_text("Python programming tutorial for beginners.")
        
        indexer.index_file(doc1)
        indexer.index_file(doc2)
        
        results = indexer.keyword_search(
            "programming",
            filter_paths=[doc1.resolve()],
        )
        
        assert len(results) >= 1
        for r in results:
            assert r.document_path == doc1.resolve()


class TestIndexerProcessIntegration:
    """Integration tests for IndexerProcess."""
    
    @pytest.fixture
    def mock_embedder(self):
        return MockEmbedder(dimensions=100)
    
    @pytest.fixture
    def config(self, tmp_path):
        return IndexerConfig(
            watcher_db_path=tmp_path / "watcher.db",
            vector_db_path=tmp_path / "vectors.db",
            embedding=EmbeddingConfig(dimensions=100),
            chunking=ChunkingConfig(chunk_size=500, min_chunk_size=10),
        )
    
    def test_full_workflow(self, config, mock_embedder, tmp_path):
        with IndexerProcess(config=config, embedder=mock_embedder) as indexer:
            # Create and index files
            doc1 = tmp_path / "intro.txt"
            doc1.write_text("Introduction to machine learning and artificial intelligence.")
            
            doc2 = tmp_path / "guide.txt"
            doc2.write_text("A comprehensive guide to deep learning techniques.")
            
            event1 = indexer.index_file(doc1)
            event2 = indexer.index_file(doc2)
            
            assert event1.chunk_count >= 1
            assert event2.chunk_count >= 1
            
            # Search - with mock embedder all embeddings are same, so all results match
            results = indexer.search("machine learning")
            # Results may be empty or have items depending on similarity threshold
            assert isinstance(results, list)
            
            # Get context
            context = indexer.get_context_for_query("artificial intelligence")
            # Context could be empty if no results above threshold
            assert isinstance(context, str)
            
            # Remove file
            indexer.remove_file(doc1)
            
            stats = indexer.get_stats()
            assert stats["document_count"] == 1
    
    def test_search_with_filter(self, config, mock_embedder, tmp_path):
        with IndexerProcess(config=config, embedder=mock_embedder) as indexer:
            doc1 = tmp_path / "doc1.txt"
            doc1.write_text("First document about Python programming.")
            
            doc2 = tmp_path / "doc2.txt"
            doc2.write_text("Second document about Java programming.")
            
            indexer.index_file(doc1)
            indexer.index_file(doc2)
            
            # Search with filter
            results = indexer.search(
                "programming",
                filter_paths=[doc1.resolve()],
            )
            
            for result in results:
                assert result.document_path == doc1.resolve()


class TestRootOverlapDetection:
    """Tests for nested/overlapping root rejection."""
    
    @pytest.fixture
    def mock_embedder(self):
        return MockEmbedder(dimensions=100)
    
    @pytest.fixture
    def config(self, tmp_path):
        return IndexerConfig(
            watcher_db_path=tmp_path / "watcher.db",
            vector_db_path=tmp_path / "vectors.db",
            embedding=EmbeddingConfig(dimensions=100),
            chunking=ChunkingConfig(chunk_size=500, min_chunk_size=10),
        )

    def test_add_root_rejects_child_of_existing(self, config, mock_embedder, tmp_path):
        """Adding a child of an existing root should raise RootOverlapError."""
        parent = tmp_path / "docs"
        child = parent / "hr"
        parent.mkdir()
        child.mkdir()
        
        with IndexerProcess(config=config, embedder=mock_embedder) as indexer:
            assert indexer.add_root(parent) is True
            
            with pytest.raises(RootOverlapError) as exc_info:
                indexer.add_root(child)
            
            assert exc_info.value.relationship == "child"
            assert str(parent) in exc_info.value.existing_root

    def test_add_root_rejects_parent_of_existing(self, config, mock_embedder, tmp_path):
        """Adding a parent of an existing root should raise RootOverlapError."""
        parent = tmp_path / "docs"
        child = parent / "hr"
        parent.mkdir()
        child.mkdir()
        
        with IndexerProcess(config=config, embedder=mock_embedder) as indexer:
            assert indexer.add_root(child) is True
            
            with pytest.raises(RootOverlapError) as exc_info:
                indexer.add_root(parent)
            
            assert exc_info.value.relationship == "parent"
            assert str(child) in exc_info.value.existing_root

    def test_add_root_allows_siblings(self, config, mock_embedder, tmp_path):
        """Sibling directories should be allowed as separate roots."""
        root_a = tmp_path / "docs" / "hr"
        root_b = tmp_path / "docs" / "finance"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        
        with IndexerProcess(config=config, embedder=mock_embedder) as indexer:
            assert indexer.add_root(root_a) is True
            assert indexer.add_root(root_b) is True

    def test_add_root_rejects_duplicate(self, config, mock_embedder, tmp_path):
        """Adding the exact same root twice should return False (not raise)."""
        root = tmp_path / "docs"
        root.mkdir()
        
        with IndexerProcess(config=config, embedder=mock_embedder) as indexer:
            assert indexer.add_root(root) is True
            assert indexer.add_root(root) is False
