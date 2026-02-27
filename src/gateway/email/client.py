"""
EmailClient — exchangelib wrapper for the bot's single mailbox.

All emails are sent from the bot account. For relay messages, user attribution
is conveyed via subject tags and body headers (no Exchange admin permissions).
"""

import logging
import time
from typing import List, Optional, Tuple

from exchangelib import (
    DELEGATE,
    Account,
    Configuration,
    Credentials,
    FaultTolerance,
    HTMLBody,
    Message,
    Mailbox,
)
from exchangelib.protocol import BaseProtocol

from .config import GatewayConfig

logger = logging.getLogger(__name__)


class EmailClient:
    """Wraps a single bot Account for reading inbox and sending emails."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._account: Optional[Account] = None

    # ── Connection ───────────────────────────────────────────────

    def connect(self) -> None:
        """Establish connection to the bot's Exchange mailbox."""
        cfg = self._config
        credentials = Credentials(username=cfg.bot_username, password=cfg.bot_password)

        if cfg.ews_server:
            from exchangelib import NTLM, BASIC

            auth_map = {"NTLM": NTLM, "basic": BASIC}
            auth_type = auth_map.get(cfg.auth_type, NTLM)
            server_config = Configuration(
                server=cfg.ews_server,
                credentials=credentials,
                auth_type=auth_type,
                retry_policy=FaultTolerance(max_wait=300),
                max_connections=cfg.max_connections,
            )
            self._account = Account(
                primary_smtp_address=cfg.bot_email,
                config=server_config,
                access_type=DELEGATE,
            )
        else:
            self._account = Account(
                primary_smtp_address=cfg.bot_email,
                credentials=credentials,
                autodiscover=True,
                access_type=DELEGATE,
            )

        logger.info("Connected to Exchange as %s", cfg.bot_email)

    @property
    def account(self) -> Account:
        if self._account is None:
            raise RuntimeError("EmailClient not connected. Call connect() first.")
        return self._account

    # ── Inbox reading ────────────────────────────────────────────

    def catch_up_sync(self) -> Optional[str]:
        """Fast catch-up: drain sync_items() to get the cursor without fetching full items."""
        inbox = self.account.inbox
        count = 0
        for _change_type, _item in inbox.sync_items():
            count += 1
        logger.info("Catch-up sync: skipped %d existing item(s)", count)
        return inbox.item_sync_state

    def sync_inbox(self, sync_state: Optional[str] = None) -> Tuple[List[Message], Optional[str]]:
        """Incremental sync of the bot's inbox.

        Returns (new_messages, new_sync_state).
        sync_items() returns lightweight stubs; we fetch full items afterward.
        """
        inbox = self.account.inbox
        if sync_state:
            inbox.item_sync_state = sync_state

        item_ids = []
        for change_type, item in inbox.sync_items():
            if change_type == "create" and isinstance(item, Message):
                item_ids.append(item)

        # Fetch full items with body, attachments, etc.
        new_items = []
        if item_ids:
            for full_item in self.account.fetch(item_ids):
                if isinstance(full_item, Message):
                    new_items.append(full_item)

        return new_items, inbox.item_sync_state

    def get_emails_after(self, after_datetime) -> List[Message]:
        """Fallback: fetch emails received after a given datetime."""
        return list(
            self.account.inbox.filter(
                datetime_received__gt=after_datetime
            ).order_by("datetime_received")
        )

    # ── Sending ──────────────────────────────────────────────────

    def send_reply(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None,
        html_body: Optional[str] = None,
    ) -> Message:
        """Send an email as the bot (agent response). Returns the sent message."""
        m = Message(
            account=self.account,
            folder=self.account.sent,
            subject=subject,
            body=HTMLBody(html_body) if html_body else body,
            to_recipients=[Mailbox(email_address=to)],
        )
        if in_reply_to:
            m.in_reply_to = in_reply_to
        m.send_and_save()
        logger.info("Sent reply to %s: %s", to, subject[:60])
        self._throttle()
        return m

    def send_relay(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None,
    ) -> Message:
        """Send a relay email (subject/body already contain [From: user] attribution)."""
        m = Message(
            account=self.account,
            folder=self.account.sent,
            subject=subject,
            body=body,
            to_recipients=[Mailbox(email_address=to)],
        )
        if in_reply_to:
            m.in_reply_to = in_reply_to
        m.send_and_save()
        logger.info("Sent relay to %s: %s", to, subject[:60])
        self._throttle()
        return m

    # ── Helpers ──────────────────────────────────────────────────

    def _throttle(self) -> None:
        if self._config.send_throttle > 0:
            time.sleep(self._config.send_throttle)

    def disconnect(self) -> None:
        if self._account and self._account.protocol:
            self._account.protocol.close()
        self._account = None
        logger.info("Disconnected from Exchange")
