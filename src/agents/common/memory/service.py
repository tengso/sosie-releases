import logging

from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types
from mem0 import Memory

from .config import get_memory_config
from .filters import is_profile_identity_memory

from google.adk.sessions.session import Session


logger = logging.getLogger(__name__)


class Mem0MemoryService(BaseMemoryService):
    """
    ADK MemoryService backed by Mem0 (self-hosted).
    
    Uses PostgreSQL (pgvector) for storage and OpenAI for embeddings/extraction.
    """

    def __init__(self):
        """
        Initialize the Mem0 memory service.
        """
        logger.info("[Mem0] Initializing Mem0MemoryService...")
        self._config = get_memory_config()
        logger.info("[Mem0] Config: llm_model=%s, embedder_model=%s, chroma_path=%s",
                     self._config["llm"]["config"]["model"],
                     self._config["embedder"]["config"]["model"],
                     self._config["vector_store"]["config"]["path"])
        self._memory = Memory.from_config(self._config)
        logger.info("[Mem0] Memory instance created successfully")

    async def add_session_to_memory(self, session: Session) -> None:
        """
        Extract and store memories from a session's conversation.
        
        Args:
            session: The ADK session containing conversation events.
        """
        logger.info(
            "[Mem0] add_session_to_memory called for session=%s, user=%s, app=%s",
            session.id, session.user_id, session.app_name
        )
        
        messages = self._extract_messages(session)
        if not messages:
            logger.info("[Mem0] No messages extracted from session %s", session.id)
            return

        logger.info("[Mem0] Extracted %d messages from session", len(messages))
        for i, msg in enumerate(messages):
            logger.info("[Mem0]   Message %d: role=%s, content=%s", i, msg["role"], msg["content"][:100])

        user_id = session.user_id
        metadata = {
            "app_name": session.app_name,
            "session_id": session.id,
        }

        try:
            logger.info("[Mem0] Calling mem0.add() for user=%s with %d messages", user_id, len(messages))
            result = self._memory.add(messages, user_id=user_id, metadata=metadata)
            logger.info("[Mem0] mem0.add() completed. Result: %s", result)
        except Exception as e:
            logger.error("[Mem0] Failed to add session to memory: %s", e, exc_info=True)
            raise

    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
    ) -> SearchMemoryResponse:
        """
        Search memories for a user.
        
        Args:
            app_name: The application name.
            user_id: The user ID to search memories for.
            query: The search query.
        
        Returns:
            SearchMemoryResponse containing matching memory entries.
        """
        logger.info("[Mem0] search_memory called: user=%s, query='%s'", user_id, query[:50])
        
        try:
            results = self._memory.search(query, user_id=user_id, limit=10)
            logger.info("[Mem0] mem0.search() returned %d results", len(results.get("results", [])))
        except Exception as e:
            logger.error("[Mem0] Failed to search memory: %s", e, exc_info=True)
            return SearchMemoryResponse(memories=[])

        memories = []
        for item in results.get("results", []):
            memory_text = item.get("memory", "")
            if not memory_text:
                continue
            if is_profile_identity_memory(memory_text):
                logger.info("[Mem0]   Skipping profile identity memory: %s", memory_text[:100])
                continue
            
            logger.debug("[Mem0]   Found memory: %s", memory_text[:100])
            entry = MemoryEntry(
                content=types.Content(
                    role="user",
                    parts=[types.Part(text=memory_text)],
                ),
                timestamp=item.get("created_at"),
            )
            memories.append(entry)

        logger.info("[Mem0] Returning %d memories for query", len(memories))
        return SearchMemoryResponse(memories=memories)

    def _extract_messages(self, session: Session) -> list[dict]:
        """
        Extract messages from session events in Mem0 format.
        
        Args:
            session: The ADK session.
        
        Returns:
            List of message dicts with 'role' and 'content' keys.
        """
        messages = []
        
        for event in session.events:
            if not event.content or not event.content.parts:
                continue
            
            text_parts = []
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
            
            if not text_parts:
                continue
            
            content = " ".join(text_parts)
            role = event.content.role or "user"
            
            if role == "model":
                role = "assistant"
            
            messages.append({"role": role, "content": content})
        
        return messages
