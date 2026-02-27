"""
Common utilities and tools shared across agents.
"""

# Register additional LiteLLM providers with ADK's model registry
from google.adk.models.registry import LLMRegistry
from google.adk.models.lite_llm import LiteLlm

LLMRegistry._register("dashscope/.*", LiteLlm)

from .tools import (
    search_chunks,
    search_documents,
    keyword_search,
    get_document_context,
    list_available_documents,
    multi_query_search,
    get_user_contact,
    send_email,
)

__all__ = [
    "search_chunks",
    "search_documents",
    "keyword_search",
    "get_document_context",
    "list_available_documents",
    "multi_query_search",
    "get_user_contact",
    "send_email",
]
