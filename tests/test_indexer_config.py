"""
Tests for indexer configuration.
"""

import pytest
import os
from pathlib import Path

from src.indexer.config import (
    IndexerConfig,
    ChunkingConfig,
    EmbeddingConfig,
    VectorStoreConfig,
)


class TestChunkingConfig:
    """Tests for ChunkingConfig."""
    
    def test_default_values(self):
        config = ChunkingConfig()
        
        assert config.chunk_size == 1000
        assert config.chunk_overlap == 200
        assert config.min_chunk_size == 100
        assert config.max_chunk_size == 2000
        assert config.split_by == "sentence"
        assert config.respect_boundaries is True
    
    def test_custom_values(self):
        config = ChunkingConfig(
            chunk_size=500,
            chunk_overlap=100,
            split_by="paragraph",
        )
        
        assert config.chunk_size == 500
        assert config.chunk_overlap == 100
        assert config.split_by == "paragraph"


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig."""
    
    def test_default_values(self):
        config = EmbeddingConfig()
        
        assert config.provider == "openai"
        assert config.model_id == "text-embedding-3-large"
        assert config.dimensions == 3072
        assert config.batch_size == 100
    
    def test_get_api_key_from_config(self):
        config = EmbeddingConfig(api_key="test-key")
        assert config.get_api_key() == "test-key"
    
    def test_get_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        config = EmbeddingConfig()
        assert config.get_api_key() == "env-key"
    
    def test_config_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        config = EmbeddingConfig(api_key="config-key")
        assert config.get_api_key() == "config-key"
    
    def test_get_proxy_from_env(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")
        config = EmbeddingConfig()
        assert config.get_https_proxy() == "http://proxy:8080"
    
    def test_get_api_base_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_BASE", "https://custom.api.com")
        config = EmbeddingConfig()
        assert config.get_api_base() == "https://custom.api.com"


class TestVectorStoreConfig:
    """Tests for VectorStoreConfig."""
    
    def test_default_values(self):
        config = VectorStoreConfig()
        
        assert config.db_path == Path("vectors.db")
        assert config.embedding_dimensions == 3072
        assert config.similarity_metric == "cosine"
    
    def test_custom_path(self, tmp_path):
        config = VectorStoreConfig(db_path=tmp_path / "custom.db")
        assert config.db_path == tmp_path / "custom.db"
    
    def test_string_path_conversion(self):
        config = VectorStoreConfig(db_path="/tmp/test.db")
        assert isinstance(config.db_path, Path)


class TestIndexerConfig:
    """Tests for IndexerConfig."""
    
    def test_default_values(self):
        config = IndexerConfig()
        
        assert config.watcher_db_path == Path("watcher.db")
        assert config.vector_db_path == Path("vectors.db")
        assert ".pdf" in config.supported_extensions
        assert ".txt" in config.supported_extensions
        assert config.max_concurrent_files == 4
    
    def test_is_supported_pdf(self):
        config = IndexerConfig()
        assert config.is_supported(Path("/test/doc.pdf")) is True
    
    def test_is_supported_txt(self):
        config = IndexerConfig()
        assert config.is_supported(Path("/test/doc.txt")) is True
    
    def test_is_supported_unsupported(self):
        config = IndexerConfig()
        assert config.is_supported(Path("/test/doc.xyz")) is False
    
    def test_is_supported_case_insensitive(self):
        config = IndexerConfig()
        assert config.is_supported(Path("/test/doc.PDF")) is True
        assert config.is_supported(Path("/test/doc.Pdf")) is True
    
    def test_get_vector_store_config(self, tmp_path):
        config = IndexerConfig(
            vector_db_path=tmp_path / "vectors.db",
            embedding=EmbeddingConfig(dimensions=1536),
        )
        
        store_config = config.get_vector_store_config()
        
        assert store_config.db_path == tmp_path / "vectors.db"
        assert store_config.embedding_dimensions == 1536
    
    def test_nested_config_from_dict(self):
        config = IndexerConfig(
            chunking={"chunk_size": 500, "chunk_overlap": 50},
            embedding={"model_id": "text-embedding-3-small"},
        )
        
        assert config.chunking.chunk_size == 500
        assert config.embedding.model_id == "text-embedding-3-small"
    
    def test_custom_supported_extensions(self):
        config = IndexerConfig(
            supported_extensions=[".doc", ".docx"]
        )
        
        assert config.is_supported(Path("/test/doc.doc")) is True
        assert config.is_supported(Path("/test/doc.pdf")) is False
