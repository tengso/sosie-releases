"""
RelayService — User↔User messaging mediated by the bot.

The bot sends as itself with text-based attribution:
- Subject: [R:token] [From: sender@firm.com] Original subject
- Body: --- Message from sender@firm.com ---\n...\n--- End ---
"""

import logging
from typing import Optional

from .client import EmailClient
from .config import GatewayConfig
from .models import InboundMessage
from .store import ConversationStore
from .util import clean_subject, generate_relay_token, wrap_relay_body

logger = logging.getLogger(__name__)


class RelayService:
    """Handles relay initiation and forwarding between two users."""

    def __init__(self, client: EmailClient, config: GatewayConfig) -> None:
        self._client = client
        self._config = config

    def initiate(
        self,
        msg: InboundMessage,
        target_email: str,
        store: ConversationStore,
    ) -> None:
        """Start a new relay conversation between msg.sender and target_email."""
        # Validate target is authorized
        if not store.is_authorized(target_email):
            logger.warning(
                "Relay target %s is not authorized, rejecting relay from %s",
                target_email, msg.sender,
            )
            self._client.send_reply(
                to=msg.sender,
                subject=f"Re: {msg.subject}",
                body=f"Relay failed: {target_email} is not an authorized user.",
                in_reply_to=msg.message_id,
            )
            return

        token = generate_relay_token(self._config.relay_token_length)

        # Create linked conversation pair
        initiator_id, target_id = store.create_relay_pair(
            initiator_conversation_id=msg.conversation_id,
            initiator_email=msg.sender,
            target_email=target_email,
            relay_token=token,
        )

        # Build relay subject and body
        subject_clean = clean_subject(msg.subject)
        relay_subject = f"[R:{token}] [From: {msg.sender}] {subject_clean}"
        relay_body = wrap_relay_body(msg.body, msg.sender)

        # Send relay email to target
        sent = self._client.send_relay(
            to=target_email,
            subject=relay_subject,
            body=relay_body,
        )
        store.touch(target_id, last_message_id=sent.message_id if hasattr(sent, 'message_id') else None)

        # Send ack to initiator
        self._client.send_reply(
            to=msg.sender,
            subject=f"Re: {msg.subject}",
            body=f"Your message has been relayed to {target_email}.",
            in_reply_to=msg.message_id,
        )
        store.touch(initiator_id, last_message_id=msg.message_id)

        # Log both directions
        store.log_message(
            direction="outbound",
            sender_email=self._config.bot_email,
            recipient_email=target_email,
            subject=relay_subject,
            body_preview=msg.body,
            conversation_id=msg.conversation_id,
            action="relay",
        )

        logger.info(
            "Relay initiated: %s → %s (token=%s, init=%d, tgt=%d)",
            msg.sender, target_email, token, initiator_id, target_id,
        )

    def forward(
        self,
        msg: InboundMessage,
        conv_id: int,
        store: ConversationStore,
    ) -> None:
        """Forward a reply in an existing relay conversation to the peer."""
        conv = store.get_by_id(conv_id)
        if conv is None:
            logger.error("Relay conversation %d not found", conv_id)
            return

        peer = store.get_by_id(conv.relay_peer_id) if conv.relay_peer_id else None
        if peer is None:
            logger.error("Relay peer not found for conversation %d", conv_id)
            return

        # Build forwarded body with attribution
        relay_body = wrap_relay_body(msg.body, msg.sender)

        # Reply in peer's thread
        self._client.send_reply(
            to=peer.owner_email,
            subject=f"Re: {msg.subject}",
            body=relay_body,
            in_reply_to=peer.last_message_id,
        )

        store.touch(conv_id, last_message_id=msg.message_id)
        store.touch(peer.id)

        store.log_message(
            direction="outbound",
            sender_email=self._config.bot_email,
            recipient_email=peer.owner_email,
            subject=msg.subject,
            body_preview=msg.body,
            conversation_id=peer.conversation_id,
            action="relay",
        )

        logger.info(
            "Relay forwarded: %s → %s (conv %d → peer %d)",
            msg.sender, peer.owner_email, conv_id, peer.id,
        )
