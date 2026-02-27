"""
Configuration for the email gateway.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GatewayConfig:
    """Configuration for the email gateway service."""

    # EWS connection
    bot_email: str  # bot-account@firm.com
    bot_username: str  # DOMAIN\\username or user@firm.com
    bot_password: str  # password
    ews_server: Optional[str] = None  # Exchange server hostname (skip autodiscover)
    auth_type: str = "NTLM"  # "NTLM" | "basic"

    # Users
    authorized_users: List[str] = field(default_factory=list)

    # Behavior
    poll_interval: float = 10.0  # seconds between inbox checks
    send_throttle: float = 1.0  # seconds between outbound emails
    max_connections: int = 3
    relay_token_length: int = 8  # hex chars for [R:xxxx] tokens

    # Integration
    adk_base_url: str = "http://localhost:8000"
    indexer_base_url: str = "http://localhost:8001"
    db_path: str = "./data/gateway.db"

    # Routing
    default_agent: str = "ask_hti_agent"
    max_attachment_chars: int = 50000  # truncation limit per attachment
