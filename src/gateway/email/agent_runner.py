"""
AgentRunner — Bridge between the email gateway and ADK agents.

Creates/resumes ADK sessions, sends composed messages (body + attachment text),
and collects the non-streaming response.
"""

import logging
import uuid
from typing import Optional

import httpx

from .config import GatewayConfig
from .models import InboundMessage
from .store import ConversationStore
from .util import compose_agent_message

logger = logging.getLogger(__name__)


class AgentConnectionError(Exception):
    """Raised when the ADK API server is not reachable."""
    pass


class AgentRunner:
    """Bridges email messages to ADK agent sessions via the ADK API server."""

    def __init__(self, config: GatewayConfig) -> None:
        self._adk_base = config.adk_base_url.rstrip("/")
        self._max_attachment_chars = config.max_attachment_chars
        self._timeout = 300.0

    def create_session(self, agent_name: str, user_id: str) -> str:
        """Create a new ADK session. Returns the session ID."""
        url = f"{self._adk_base}/apps/{agent_name}/users/{user_id}/sessions"
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json={}, headers={"Content-Type": "application/json"})
                resp.raise_for_status()
                data = resp.json()
                session_id = data.get("id", str(uuid.uuid4()))
                logger.info("Created ADK session %s for %s/%s", session_id, agent_name, user_id)
                return session_id
        except httpx.ConnectError:
            raise AgentConnectionError(
                f"Cannot connect to ADK API server at {self._adk_base}. "
                f"Make sure the agent server is running: python -m src.cli api-server"
            )
        except httpx.HTTPStatusError as e:
            raise AgentConnectionError(
                f"ADK API server returned HTTP {e.response.status_code} "
                f"when creating session for agent '{agent_name}': {e.response.text[:200]}"
            )

    def run(
        self,
        msg: InboundMessage,
        agent_name: str,
        session_id: str,
        user_id: str,
    ) -> str:
        """Send message to agent via non-streaming endpoint and return the response."""
        composed = compose_agent_message(
            body=msg.body,
            attachments=msg.attachments,
            max_chars=self._max_attachment_chars,
        )

        logger.info(
            "Sending to agent %s (session=%s, user=%s):\n%s",
            agent_name, session_id, user_id, composed,
        )

        return self._send(agent_name, user_id, session_id, composed)

    def _send(
        self,
        agent_name: str,
        user_id: str,
        session_id: str,
        message_text: str,
    ) -> str:
        """Send a message to the ADK API (non-streaming) and return the response."""
        url = f"{self._adk_base}/run"
        payload = {
            "appName": agent_name,
            "userId": user_id,
            "sessionId": session_id,
            "newMessage": {
                "role": "user",
                "parts": [{"text": message_text}],
            },
            "streaming": False,
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            raise AgentConnectionError(
                f"Cannot connect to ADK API server at {self._adk_base}. "
                f"Make sure the agent server is running: python -m src.cli api-server"
            )
        except httpx.HTTPStatusError as e:
            raise AgentConnectionError(
                f"ADK API server returned HTTP {e.response.status_code} "
                f"for agent '{agent_name}': {e.response.text[:200]}"
            )

        # Extract text parts from all response events
        texts = []
        events = data if isinstance(data, list) else [data]
        for event in events:
            content = event.get("content", {})
            if isinstance(content, dict) and "parts" in content:
                for part in content["parts"]:
                    if isinstance(part, dict) and "text" in part:
                        text = part["text"].strip()
                        if text:
                            texts.append(text)

        full_response = "\n\n".join(texts)

        logger.info(
            "Agent %s responded with %d chars (%d part(s)) for session %s",
            agent_name, len(full_response), len(texts), session_id,
        )
        return full_response

    def create_and_run(
        self,
        msg: InboundMessage,
        agent_name: str,
        store: ConversationStore,
    ) -> tuple:
        """Create a new session and run the agent. Returns (session_id, response_text)."""
        user_id = msg.sender
        session_id = self.create_session(agent_name, user_id)

        conv_id = store.create_agent_conversation(
            conversation_id=msg.conversation_id,
            owner_email=msg.sender,
            agent_name=agent_name,
            adk_session_id=session_id,
            adk_user_id=user_id,
        )

        response = self.run(msg, agent_name, session_id, user_id)
        store.touch(conv_id, last_message_id=msg.message_id)

        return session_id, response

    def resume_and_run(
        self,
        msg: InboundMessage,
        conv_id: int,
        agent_name: str,
        session_id: str,
        user_id: str,
        store: ConversationStore,
    ) -> str:
        """Resume an existing session and run the agent. Returns response text."""
        response = self.run(msg, agent_name, session_id, user_id)
        store.touch(conv_id, last_message_id=msg.message_id)
        return response
