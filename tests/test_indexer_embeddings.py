"""
Tests for indexer embeddings.
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock

from src.indexer.embeddings import BaseEmbedder, OpenAIEmbedder, create_embedder
from src.indexer.exceptions import EmbeddingAuthError, EmbeddingAPIError


class MockEmbedder(BaseEmbedder):
    """Mock embedder for testing."""
    
    def __init__(self, dimensions: int = 100):
        self._dimensions = dimensions
    
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
        return [[0.1] * self._dimensions for _ in texts]


class TestBaseEmbedder:
    """Tests for BaseEmbedder."""
    
    def test_embed_single(self):
        embedder = MockEmbedder()
        result = embedder.embed_single("Test text")
        
        assert len(result) == 100
        assert result == [0.1] * 100
    
    def test_embed_multiple(self):
        embedder = MockEmbedder()
        results = embedder.embed(["Text 1", "Text 2", "Text 3"])
        
        assert len(results) == 3
        assert all(len(r) == 100 for r in results)
    
    def test_model_id(self):
        embedder = MockEmbedder()
        assert embedder.model_id == "mock-model"
    
    def test_dimensions(self):
        embedder = MockEmbedder(dimensions=256)
        assert embedder.dimensions == 256


class TestOpenAIEmbedder:
    """Tests for OpenAIEmbedder."""
    
    def test_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        
        with pytest.raises(EmbeddingAuthError, match="API key"):
            OpenAIEmbedder()
    
    def test_accepts_api_key_param(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = OpenAIEmbedder(api_key="test-key")
            assert embedder._api_key == "test-key"
    
    def test_accepts_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = OpenAIEmbedder()
            assert embedder._api_key == "env-key"
    
    def test_model_id(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = OpenAIEmbedder(model="text-embedding-3-small")
            assert embedder.model_id == "text-embedding-3-small"
    
    def test_dimensions_large_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = OpenAIEmbedder(model="text-embedding-3-large")
            assert embedder.dimensions == 3072
    
    def test_dimensions_small_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = OpenAIEmbedder(model="text-embedding-3-small")
            assert embedder.dimensions == 1536
    
    def test_proxy_configuration(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = OpenAIEmbedder()
            assert embedder._https_proxy == "http://proxy:8080"
    
    def test_embed_empty_list(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = OpenAIEmbedder()
            result = embedder.embed([])
            assert result == []
    
    def test_context_manager(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            with OpenAIEmbedder() as embedder:
                assert embedder is not None


class TestCreateEmbedder:
    """Tests for create_embedder factory function."""
    
    def test_create_openai_embedder(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = create_embedder("openai")
            assert isinstance(embedder, OpenAIEmbedder)
    
    def test_create_unknown_provider(self):
        with pytest.raises(ValueError, match="Unsupported"):
            create_embedder("unknown")
    
    def test_create_with_kwargs(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        with patch('src.indexer.embeddings.openai.OpenAI'):
            embedder = create_embedder(
                "openai",
                model="text-embedding-3-small",
                batch_size=50,
            )
            assert embedder.model_id == "text-embedding-3-small"
            assert embedder._batch_size == 50
