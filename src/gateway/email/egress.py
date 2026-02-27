"""
Egress — Outbound email formatting and sending.

- Agent responses: bot replies as itself (no attribution needed)
- Relay: handled by RelayService (text-based attribution in subject/body)
- Help: sends usage instructions
"""

import logging
from typing import Optional

from .client import EmailClient
from .config import GatewayConfig
from .models import InboundMessage
from .store import ConversationStore
from .util import markdown_to_html

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Email Gateway — Usage Guide

Send an email to this bot with one of the following subject tags:

  [QA] Your question here
    → Ask the document Q&A agent

  [Research] Your topic here
    → Start a deep research session

  [To: user@firm.com] Message
    → Relay a message to another authorized user

  [Help]
    → Show this help message

You can also reply to any existing conversation to continue it.
If no tag is provided, your message will be routed to the default Q&A agent.
"""


class Egress:
    """Sends outbound emails from the gateway."""

    def __init__(self, client: EmailClient, config: GatewayConfig) -> None:
        self._client = client
        self._config = config

    def send_agent_response(
        self,
        original: InboundMessage,
        response_text: str,
        store: ConversationStore,
    ) -> None:
        """Reply to the user with the agent's response (markdown → HTML)."""
        html_body = markdown_to_html(response_text)
        self._client.send_reply(
            to=original.sender,
            subject=f"Re: {original.subject}",
            body=response_text,
            html_body=html_body,
            in_reply_to=original.message_id,
        )

        store.log_message(
            direction="outbound",
            sender_email=self._config.bot_email,
            recipient_email=original.sender,
            subject=original.subject,
            body_preview=response_text,
            conversation_id=original.conversation_id,
            action="agent_response",
        )

    def send_help(
        self,
        original: InboundMessage,
        store: ConversationStore,
    ) -> None:
        """Send help/usage instructions to the user."""
        self._client.send_reply(
            to=original.sender,
            subject=f"Re: {original.subject}",
            body=HELP_TEXT,
            in_reply_to=original.message_id,
        )

        store.log_message(
            direction="outbound",
            sender_email=self._config.bot_email,
            recipient_email=original.sender,
            subject=original.subject,
            body_preview=HELP_TEXT,
            conversation_id=original.conversation_id,
            action="help",
        )

    def send_error(
        self,
        original: InboundMessage,
        error_message: str,
        store: ConversationStore,
    ) -> None:
        """Send an error notification to the user."""
        body = f"An error occurred while processing your message:\n\n{error_message}"
        self._client.send_reply(
            to=original.sender,
            subject=f"Re: {original.subject}",
            body=body,
            in_reply_to=original.message_id,
        )

        store.log_message(
            direction="outbound",
            sender_email=self._config.bot_email,
            recipient_email=original.sender,
            subject=original.subject,
            body_preview=body,
            conversation_id=original.conversation_id,
            action="error",
        )
