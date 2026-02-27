"""
Router — Demux + intent classification for inbound emails.

Lookup order:
1. conversation_id → existing conversation (resume)
2. relay token [R:xxxx] in subject → relay resume + backfill
3. Subject tags [QA], [Research], [To: user@] → new conversation
4. Fallback → default agent
"""

import logging
from typing import Optional

from .models import InboundMessage, RoutingDecision
from .store import ConversationStore
from .util import (
    is_help_request,
    parse_agent_tag,
    parse_relay_target,
    parse_relay_token,
)

logger = logging.getLogger(__name__)


class Router:
    """Classifies inbound emails into routing decisions."""

    def __init__(self, default_agent: str = "ask_hti_agent") -> None:
        self._default_agent = default_agent

    def classify(self, msg: InboundMessage, store: ConversationStore) -> RoutingDecision:
        """Determine what to do with an inbound email.

        Returns a RoutingDecision indicating whether to resume an existing
        conversation or create a new one (agent, relay, or help).
        """
        # 1. Lookup by conversation_id
        if msg.conversation_id:
            conv = store.get_by_conversation_id(msg.conversation_id)
            if conv is not None:
                logger.info(
                    "Resuming %s conversation %d for %s (conv_id=%s)",
                    conv.type, conv.id, conv.owner_email, msg.conversation_id,
                )
                return RoutingDecision(
                    action=f"resume_{conv.type.split('_')[0]}",
                    agent_name=conv.agent_name,
                    conversation_id=msg.conversation_id,
                    existing_conversation_id=conv.id,
                )

        # 2. Lookup by relay token
        token = parse_relay_token(msg.subject)
        if token:
            conv = store.get_by_relay_token(token)
            if conv is not None:
                # Backfill conversation_id on first reply from target
                if msg.conversation_id and not conv.conversation_id:
                    store.backfill_conversation_id(conv.id, msg.conversation_id)
                    logger.info(
                        "Backfilled conversation_id %s on relay conv %d",
                        msg.conversation_id, conv.id,
                    )
                logger.info(
                    "Resuming relay conversation %d via token %s",
                    conv.id, token,
                )
                return RoutingDecision(
                    action="resume_relay",
                    conversation_id=msg.conversation_id,
                    existing_conversation_id=conv.id,
                )

        # 3. New conversation — classify from subject tags
        # Check for relay target
        relay_target = parse_relay_target(msg.subject)
        if relay_target:
            logger.info("New relay from %s to %s", msg.sender, relay_target)
            return RoutingDecision(
                action="relay",
                target_user=relay_target,
                conversation_id=msg.conversation_id,
            )

        # Check for help request
        if is_help_request(msg.subject):
            logger.info("Help request from %s", msg.sender)
            return RoutingDecision(
                action="help",
                conversation_id=msg.conversation_id,
            )

        # Check for agent tag
        agent_name = parse_agent_tag(msg.subject)
        if agent_name:
            logger.info("New %s session for %s", agent_name, msg.sender)
            return RoutingDecision(
                action="agent",
                agent_name=agent_name,
                conversation_id=msg.conversation_id,
            )

        # 4. Fallback — default agent
        logger.info("No tag found, routing to default agent for %s", msg.sender)
        return RoutingDecision(
            action="agent",
            agent_name=self._default_agent,
            conversation_id=msg.conversation_id,
        )
