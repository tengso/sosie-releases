"""
GatewayService — Main orchestrator.

Poll loop: fetch → demux/route → process → respond.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .agent_runner import AgentConnectionError, AgentRunner
from .client import EmailClient
from .config import GatewayConfig
from .egress import Egress
from .ingress import Ingress
from .models import InboundMessage, RoutingDecision
from .relay import RelayService
from .router import Router
from .store import ConversationStore

logger = logging.getLogger(__name__)


class GatewayService:
    """Orchestrates the email gateway poll → route → process → respond loop."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._store = ConversationStore(config.db_path)
        self._client = EmailClient(config)
        self._ingress = Ingress(
            self._client, self._store, set(config.authorized_users),
        )
        self._router = Router(config.default_agent)
        self._agent_runner = AgentRunner(config)
        self._relay = RelayService(self._client, config)
        self._egress = Egress(self._client, config)
        self._executor = ThreadPoolExecutor(max_workers=2)

    def setup(self) -> None:
        """Connect to Exchange and seed authorized users from config."""
        self._client.connect()

        for email in self._config.authorized_users:
            self._store.add_authorized_user(email)
            logger.info("Authorized user: %s", email)

    async def run(self) -> None:
        """Main async loop: poll inbox, route, process, respond."""
        logger.info(
            "Gateway service started (poll_interval=%.1fs)",
            self._config.poll_interval,
        )

        loop = asyncio.get_event_loop()

        while True:
            try:
                messages = await loop.run_in_executor(
                    self._executor, self._ingress.fetch_new
                )

                for msg in messages:
                    try:
                        await self._process_message(msg, loop)
                    except AgentConnectionError as e:
                        logger.error(
                            "Agent server unavailable while processing message from %s: %s",
                            msg.sender, e,
                        )
                        try:
                            user_msg = (
                                "Your message was received but the AI agent service is currently unavailable. "
                                "Please try again later or contact your administrator.\n\n"
                                f"Technical detail: {e}"
                            )
                            await loop.run_in_executor(
                                self._executor,
                                self._egress.send_error, msg, user_msg, self._store,
                            )
                        except Exception:
                            logger.error("Failed to send error reply", exc_info=True)
                    except Exception as e:
                        logger.error(
                            "Error processing message from %s: %s",
                            msg.sender, e, exc_info=True,
                        )
                        try:
                            await loop.run_in_executor(
                                self._executor,
                                self._egress.send_error, msg, str(e), self._store,
                            )
                        except Exception:
                            logger.error("Failed to send error reply", exc_info=True)

            except Exception as e:
                logger.error("Error in poll cycle: %s", e, exc_info=True)

            await asyncio.sleep(self._config.poll_interval)

    async def _process_message(
        self,
        msg: InboundMessage,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Route and process a single inbound message."""
        # Log inbound
        self._store.log_message(
            direction="inbound",
            sender_email=msg.sender,
            recipient_email=self._config.bot_email,
            subject=msg.subject,
            body_preview=msg.body,
            conversation_id=msg.conversation_id,
            has_attachments=bool(msg.attachments),
            exchange_msg_id=msg.message_id,
        )

        decision = self._router.classify(msg, self._store)
        logger.info(
            "Routing %s from %s → %s",
            msg.conversation_id[:12] if msg.conversation_id else "new",
            msg.sender,
            decision.action,
        )

        if decision.action == "agent":
            await self._handle_new_agent(msg, decision, loop)
        elif decision.action == "resume_agent":
            await self._handle_resume_agent(msg, decision, loop)
        elif decision.action == "relay":
            await loop.run_in_executor(
                self._executor,
                self._relay.initiate, msg, decision.target_user, self._store,
            )
        elif decision.action in ("resume_relay", "resume_relay_initiator", "resume_relay_target"):
            await loop.run_in_executor(
                self._executor,
                self._relay.forward, msg, decision.existing_conversation_id, self._store,
            )
        elif decision.action == "help":
            await loop.run_in_executor(
                self._executor,
                self._egress.send_help, msg, self._store,
            )
        else:
            logger.warning("Unknown routing action: %s", decision.action)

    async def _handle_new_agent(
        self,
        msg: InboundMessage,
        decision: RoutingDecision,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Create a new agent session and send the first response."""
        agent_name = decision.agent_name or self._config.default_agent

        session_id, response = await loop.run_in_executor(
            self._executor,
            self._agent_runner.create_and_run, msg, agent_name, self._store,
        )

        await loop.run_in_executor(
            self._executor,
            self._egress.send_agent_response, msg, response, self._store,
        )

    async def _handle_resume_agent(
        self,
        msg: InboundMessage,
        decision: RoutingDecision,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Resume an existing agent session."""
        conv = self._store.get_by_id(decision.existing_conversation_id)
        if conv is None:
            logger.error("Conversation %d not found for resume", decision.existing_conversation_id)
            return

        response = await loop.run_in_executor(
            self._executor,
            self._agent_runner.resume_and_run,
            msg, conv.id, conv.agent_name, conv.adk_session_id, conv.adk_user_id, self._store,
        )

        await loop.run_in_executor(
            self._executor,
            self._egress.send_agent_response, msg, response, self._store,
        )

    def shutdown(self) -> None:
        """Clean up resources."""
        self._client.disconnect()
        self._store.close()
        self._executor.shutdown(wait=False)
        logger.info("Gateway service stopped")
