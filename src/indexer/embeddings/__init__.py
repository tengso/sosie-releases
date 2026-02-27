"""
Embedding providers for the indexer package.
"""

from .base import BaseEmbedder
from .openai import OpenAIEmbedder

__all__ = [
    "BaseEmbedder",
    "OpenAIEmbedder",
]


def create_embedder(provider: str = "openai", **kwargs) -> BaseEmbedder:
    """
    Create an embedder instance.
    
    Args:
        provider: Embedder provider name ("openai")
        **kwargs: Provider-specific arguments
        
    Returns:
        Embedder instance
        
    Raises:
        ValueError: If provider is not supported
    """
    if provider == "openai":
        return OpenAIEmbedder(**kwargs)
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")
