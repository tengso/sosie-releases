"""
Custom service registration for ADK.

This module is automatically loaded by ADK CLI when starting the server.
It registers custom services with the global service registry.
"""

import logging

from google.adk.cli.service_registry import get_service_registry

from src.agents.common.memory import Mem0MemoryService

logger = logging.getLogger(__name__)


def _mem0_memory_factory(uri: str, **kwargs):
    """Factory function for creating Mem0MemoryService instances."""
    logger.info("[Mem0] Factory invoked with uri=%s, creating Mem0MemoryService...", uri)
    service = Mem0MemoryService()
    logger.info("[Mem0] Mem0MemoryService created successfully")
    return service


# Register custom services
logger.info("[Mem0] Registering mem0 memory service factory with ADK service registry")
registry = get_service_registry()
registry.register_memory_service("mem0", _mem0_memory_factory)
logger.info("[Mem0] mem0 memory service factory registered")
