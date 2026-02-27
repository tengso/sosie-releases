"""
Ingress — Inbound email poller.

Polls the bot's inbox via sync_items() for incremental sync,
parses raw emails into InboundMessage objects, and rejects unauthorized senders.
"""

import logging
from typing import List, Optional, Set

from exchangelib import FileAttachment, HTMLBody, Message

from .client import EmailClient
from .models import Attachment, InboundMessage
from .store import ConversationStore
from .util import extract_body_text, html_to_text

logger = logging.getLogger(__name__)


class Ingress:
    """Fetches and parses new emails from the bot's inbox."""

    def __init__(
        self,
        client: EmailClient,
        store: ConversationStore,
        authorized_emails: Optional[Set[str]] = None,
    ) -> None:
        self._client = client
        self._store = store
        self._authorized: Set[str] = {e.lower() for e in (authorized_emails or set())}

    def fetch_new(self) -> List[InboundMessage]:
        """Poll for new emails, filter, and parse into InboundMessage objects."""
        folder_id = str(self._client.account.inbox.id)
        sync_state = self._store.get_sync_state(folder_id)

        if sync_state is None:
            # First run — fast catch-up to current state without processing
            logger.info("First run: catching up inbox sync state (skipping existing emails)")
            new_sync_state = self._client.catch_up_sync()
            if new_sync_state:
                self._store.set_sync_state(folder_id, new_sync_state)
            return []

        raw_messages, new_sync_state = self._client.sync_inbox(sync_state)

        if new_sync_state:
            self._store.set_sync_state(folder_id, new_sync_state)

        results: List[InboundMessage] = []
        for msg in raw_messages:
            parsed = self._parse_message(msg)
            if parsed is None:
                continue

            if not self._is_authorized(parsed.sender):
                logger.warning("Rejected email from unauthorized sender: %s", parsed.sender)
                self._store.log_message(
                    direction="inbound",
                    sender_email=parsed.sender,
                    recipient_email=self._client._config.bot_email,
                    subject=parsed.subject,
                    action="rejected",
                )
                continue

            results.append(parsed)

        if results:
            logger.info("Fetched %d new authorized email(s)", len(results))
        return results

    def _is_authorized(self, sender_email: str) -> bool:
        """Check if sender is in the authorized list (config or DB)."""
        if sender_email.lower() in self._authorized:
            return True
        return self._store.is_authorized(sender_email)

    def _parse_message(self, msg: Message) -> Optional[InboundMessage]:
        """Convert an exchangelib Message to an InboundMessage."""
        try:
            sender = msg.sender.email_address if msg.sender else None
            if not sender:
                logger.warning("Skipping message with no sender: %s", msg.subject)
                return None

            attachments = self._extract_attachments(msg)

            # exchangelib: msg.body is either HTMLBody (str subclass) or plain str
            raw_body = str(msg.body) if msg.body else ""
            is_html = isinstance(msg.body, HTMLBody)

            if is_html:
                body_text = html_to_text(raw_body)
                html_body_str = raw_body
            else:
                body_text = raw_body.strip()
                html_body_str = None

            return InboundMessage(
                sender=sender.lower(),
                subject=msg.subject or "",
                body=body_text,
                html_body=html_body_str,
                conversation_id=msg.conversation_id.id if msg.conversation_id else "",
                message_id=msg.message_id or "",
                in_reply_to=msg.in_reply_to if hasattr(msg, "in_reply_to") else None,
                attachments=attachments,
                received_at=msg.datetime_received,
            )
        except Exception as e:
            logger.error("Failed to parse message: %s", e, exc_info=True)
            return None

    def _extract_attachments(self, msg: Message) -> List[Attachment]:
        """Extract file attachments from an exchangelib Message."""
        attachments: List[Attachment] = []
        if not msg.attachments:
            return attachments

        for att in msg.attachments:
            if isinstance(att, FileAttachment):
                try:
                    attachments.append(Attachment(
                        filename=att.name or "unnamed",
                        content=att.content,
                        content_type=att.content_type or "application/octet-stream",
                    ))
                except Exception as e:
                    logger.warning("Failed to read attachment %s: %s", att.name, e)

        return attachments
