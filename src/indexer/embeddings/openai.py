"""
OpenAI embedding provider.
"""

import logging
import os
import time
from typing import List, Optional

import httpx
from openai import OpenAI

from .base import BaseEmbedder

logger = logging.getLogger(__name__)
from ..exceptions import (
    EmbeddingError,
    EmbeddingAPIError,
    EmbeddingRateLimitError,
    EmbeddingAuthError,
)


class OpenAIEmbedder(BaseEmbedder):
    """
    OpenAI embedding provider.
    
    Environment variables:
    - OPENAI_API_KEY: API key (required if not passed)
    - OPENAI_API_BASE: Base URL (optional)
    - HTTP_PROXY: HTTP proxy URL (optional)
    - HTTPS_PROXY: HTTPS proxy URL (optional)
    """
    
    MODEL_DIMENSIONS = {
        "text-embedding-3-large": 3072,
        "text-embedding-3-small": 1536,
        "text-embedding-ada-002": 1536,
        "text-embedding-v4": 1024,
    }
    
    MODEL_MAX_TOKENS = {
        "text-embedding-3-large": 8191,
        "text-embedding-3-small": 8191,
        "text-embedding-ada-002": 8191,
        "text-embedding-v4": 8192,
    }
    
    def __init__(
        self,
        model: str = "text-embedding-3-large",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        batch_size: int = 100,
    ):
        """
        Initialize OpenAI embedder.
        
        Args:
            model: Model name
            api_key: API key (falls back to OPENAI_API_KEY env var)
            api_base: API base URL (falls back to OPENAI_API_BASE env var)
            http_proxy: HTTP proxy (falls back to HTTP_PROXY env var)
            https_proxy: HTTPS proxy (falls back to HTTPS_PROXY env var)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            batch_size: Maximum texts per API call
        """
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._batch_size = batch_size
        
        # Get API key
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        logger.debug(f"OpenAIEmbedder init: model={model}, api_key={'[SET]' if self._api_key else '[NOT SET]'}")
        if not self._api_key:
            logger.error("OpenAI API key not provided")
            raise EmbeddingAuthError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable.")
        
        # Get base URL
        self._api_base = api_base or os.environ.get("OPENAI_API_BASE")
        
        # Get proxy settings
        self._http_proxy = http_proxy or os.environ.get("HTTP_PROXY")
        self._https_proxy = https_proxy or os.environ.get("HTTPS_PROXY")
        
        # Create HTTP client with proxy support
        self._http_client = self._create_http_client()
        
        # Create OpenAI client
        self._client = OpenAI(
            api_key=self._api_key,
            base_url=self._api_base,
            http_client=self._http_client,
            timeout=self._timeout,
            max_retries=0,  # We handle retries ourselves
        )
    
    def _create_http_client(self) -> httpx.Client:
        """Create HTTP client with proxy configuration."""
        proxies = {}
        if self._http_proxy:
            proxies["http://"] = self._http_proxy
        if self._https_proxy:
            proxies["https://"] = self._https_proxy
        
        if proxies:
            return httpx.Client(proxy=self._https_proxy or self._http_proxy)
        return httpx.Client()
    
    @property
    def model_id(self) -> str:
        """Return model identifier."""
        return self._model
    
    @property
    def dimensions(self) -> int:
        """Return embedding dimensions."""
        return self.MODEL_DIMENSIONS.get(self._model, 3072)
    
    @property
    def max_tokens(self) -> int:
        """Return maximum input tokens supported by the model."""
        return self.MODEL_MAX_TOKENS.get(self._model, 8191)
    
    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
            
        Raises:
            EmbeddingError: If embedding fails
        """
        logger.debug(f"embed called with {len(texts)} texts")
        if not texts:
            return []
        
        # Process in batches
        all_embeddings = []
        
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            batch_embeddings = self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)
        
        return all_embeddings
    
    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a single batch of texts.
        
        Args:
            texts: Batch of texts
            
        Returns:
            List of embeddings
        """
        last_error = None
        
        for attempt in range(self._max_retries):
            try:
                response = self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                )
                
                # Sort by index to ensure correct order
                embeddings_data = sorted(response.data, key=lambda x: x.index)
                return [item.embedding for item in embeddings_data]
                
            except Exception as e:
                logger.error(f"Embedding API error (attempt {attempt + 1}/{self._max_retries}): {e}")
                last_error = e
                error_message = str(e).lower()
                
                # Check for auth errors
                if "unauthorized" in error_message or "invalid api key" in error_message:
                    raise EmbeddingAuthError(f"Authentication failed: {e}")
                
                # Check for rate limit
                if "rate limit" in error_message or "429" in error_message:
                    retry_after = self._get_retry_after(e)
                    if attempt < self._max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise EmbeddingRateLimitError(
                        f"Rate limit exceeded: {e}",
                        status_code=429,
                        retry_after=retry_after,
                    )
                
                # Retry on transient errors
                if attempt < self._max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    time.sleep(wait_time)
                    continue
        
        raise EmbeddingAPIError(f"Failed to generate embeddings after {self._max_retries} attempts: {last_error}")
    
    def _get_retry_after(self, error: Exception) -> float:
        """Extract retry-after time from error."""
        # Try to extract from error message or headers
        try:
            error_str = str(error)
            if "retry after" in error_str.lower():
                # Try to parse retry time
                import re
                match = re.search(r'retry after (\d+)', error_str.lower())
                if match:
                    return float(match.group(1))
        except Exception:
            pass
        
        # Default retry time
        return 60.0
    
    def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            self._http_client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
