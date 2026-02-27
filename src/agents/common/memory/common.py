import logging

logger = logging.getLogger(__name__)


async def persist_memory(callback_context):
    """Persist conversation to memory after each agent turn."""
    logger.info("[Mem0] persist_memory callback invoked")

    inv = callback_context._invocation_context
    logger.info(
        "[Mem0] persist_memory: session=%s, user=%s, memory_service=%s",
        inv.session.id if inv.session else None,
        inv.session.user_id if inv.session else None,
        type(inv.memory_service).__name__ if inv.memory_service else "None",
    )

    if inv.memory_service is None:
        logger.warning("[Mem0] persist_memory: No memory service configured — skipping")
        return None

    try:
        await callback_context.add_session_to_memory()
        logger.info("[Mem0] persist_memory: Session saved to memory successfully")
    except Exception as e:
        logger.warning("[Mem0] persist_memory: Failed to save session to memory: %s", e, exc_info=True)
    return None

