"""
Data models for the email gateway.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


@dataclass
class Attachment:
    """An email attachment."""
    filename: str
    content: bytes
    content_type: str


@dataclass
class InboundMessage:
    """Parsed inbound email from the bot's inbox."""
    sender: str
    subject: str
    body: str
    html_body: Optional[str]
    conversation_id: str
    message_id: str
    in_reply_to: Optional[str]
    attachments: List[Attachment] = field(default_factory=list)
    received_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OutboundMessage:
    """Email to be sent by the bot."""
    to: str
    subject: str
    body: str
    html_body: Optional[str] = None
    in_reply_to: Optional[str] = None
    from_user: Optional[str] = None  # for relay attribution in subject/body


@dataclass
class RoutingDecision:
    """Result of classifying an inbound email."""
    action: str  # 'agent' | 'relay' | 'help' | 'resume_agent' | 'resume_relay'
    agent_name: Optional[str] = None
    target_user: Optional[str] = None
    conversation_id: Optional[str] = None
    # Set when resuming an existing conversation
    existing_conversation_id: Optional[int] = None


@dataclass
class ConversationRow:
    """A row from the conversations table."""
    id: int
    conversation_id: Optional[str]
    relay_token: Optional[str]
    type: str  # 'agent' | 'relay_initiator' | 'relay_target'
    owner_email: str
    state: str  # 'active' | 'closed'
    agent_name: Optional[str]
    adk_session_id: Optional[str]
    adk_user_id: Optional[str]
    relay_peer_id: Optional[int]
    relay_target_email: Optional[str]
    created_at: str
    last_active: str
    last_message_id: Optional[str]
