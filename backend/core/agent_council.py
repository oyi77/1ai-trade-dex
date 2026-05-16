"""Multi-Agent Council — typed message routing and agent orchestration.

Implements ADR-012: decomposes the monolithic AGI orchestrator into a council
of 6 specialized agents communicating via typed messages.

Agents:
    AnalystAgent      — market analysis, signal generation
    SynthesizerAgent  — strategy synthesis, code generation
    CriticAgent       — review and challenge proposals (veto power)
    ExecutorAgent     — trade execution decisions
    HistorianAgent    — knowledge graph management, pattern storage
    EvolverAgent      — genome evolution, strategy optimization

Infrastructure:
    MessageBus        — typed message routing between agents
    AuthorityHierarchy — defines override rules
    AgentCouncil      — orchestrates message flow, manages agent lifecycle
"""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from loguru import logger

from backend.monitoring.agi_metrics import (
    record_council_message,
    record_council_response_time,
    record_council_authority_rejection,
    set_council_queue_depth,
)


# ---------------------------------------------------------------------------
# Message protocol
# ---------------------------------------------------------------------------

class MessageType(Enum):
    """Typed message categories flowing through the council."""
    SIGNAL = "signal"
    PROPOSAL = "proposal"
    CRITIQUE = "critique"
    EXECUTION_ORDER = "execution_order"
    LESSON = "lesson"
    EVOLUTION_REQUEST = "evolution_request"
    STATUS_REQUEST = "status_request"
    STATUS_RESPONSE = "status_response"


class AuthorityLevel(Enum):
    """Agent authority tiers in the council hierarchy."""
    ADVISORY = "advisory"        # produces signals/proposals, cannot execute
    VETO = "veto"                # can reject any proposal
    EXECUTION = "execution"      # sole execution authority


@dataclass
class AgentMessage:
    """Typed message routed between agents via the MessageBus."""
    source_agent: str
    target_agent: str                          # agent role or "broadcast"
    message_type: MessageType
    payload: dict[str, Any]
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 300

    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return elapsed > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        }


# ---------------------------------------------------------------------------
# Base agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """Abstract base class for all council agents."""

    def __init__(self) -> None:
        self._message_log: list[AgentMessage] = []

    @abstractmethod
    async def handle_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Process an incoming message; return a response message or None."""

    @abstractmethod
    def get_role(self) -> str:
        """Return the unique agent role identifier."""

    @abstractmethod
    def get_authority(self) -> AuthorityLevel:
        """Return this agent's authority level."""

    def can_handle(self, message: AgentMessage) -> bool:
        """Check if this agent can handle the given message type.

        Default: accept broadcast messages or messages targeted to this agent.
        Subclasses may override for additional filtering.
        """
        if message.is_expired():
            return False
        return message.target_agent in ("broadcast", self.get_role())

    def get_status(self) -> dict[str, Any]:
        """Return agent status for diagnostics."""
        return {
            "role": self.get_role(),
            "authority": self.get_authority().value,
            "messages_processed": len(self._message_log),
        }


# ---------------------------------------------------------------------------
# Concrete agents
# ---------------------------------------------------------------------------

class AnalystAgent(BaseAgent):
    """Market analysis, signal generation, market scanning."""

    async def handle_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        self._message_log.append(message)
        if message.message_type == MessageType.STATUS_REQUEST:
            return AgentMessage(
                source_agent=self.get_role(),
                target_agent=message.source_agent,
                message_type=MessageType.STATUS_RESPONSE,
                payload=self.get_status(),
                correlation_id=message.correlation_id,
            )
        # Produce market signals from payload (market_data, regime, etc.)
        logger.debug("AnalystAgent processing %s from %s", message.message_type.value, message.source_agent)
        return None

    def get_role(self) -> str:
        return "analyst"

    def get_authority(self) -> AuthorityLevel:
        return AuthorityLevel.ADVISORY


class SynthesizerAgent(BaseAgent):
    """Strategy composition, genome ideation, prompt evolution."""

    async def handle_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        self._message_log.append(message)
        if message.message_type == MessageType.STATUS_REQUEST:
            return AgentMessage(
                source_agent=self.get_role(),
                target_agent=message.source_agent,
                message_type=MessageType.STATUS_RESPONSE,
                payload=self.get_status(),
                correlation_id=message.correlation_id,
            )
        logger.debug("SynthesizerAgent processing %s from %s", message.message_type.value, message.source_agent)
        return None

    def get_role(self) -> str:
        return "synthesizer"

    def get_authority(self) -> AuthorityLevel:
        return AuthorityLevel.ADVISORY


class CriticAgent(BaseAgent):
    """Risk critique, validation against bounds, coherence checks. Veto power."""

    async def handle_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        self._message_log.append(message)
        if message.message_type == MessageType.STATUS_REQUEST:
            return AgentMessage(
                source_agent=self.get_role(),
                target_agent=message.source_agent,
                message_type=MessageType.STATUS_RESPONSE,
                payload=self.get_status(),
                correlation_id=message.correlation_id,
            )
        logger.debug("CriticAgent processing %s from %s", message.message_type.value, message.source_agent)
        return None

    def get_role(self) -> str:
        return "critic"

    def get_authority(self) -> AuthorityLevel:
        return AuthorityLevel.VETO


class ExecutorAgent(BaseAgent):
    """Trade execution, order management, position tracking."""

    async def handle_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        self._message_log.append(message)
        if message.message_type == MessageType.STATUS_REQUEST:
            return AgentMessage(
                source_agent=self.get_role(),
                target_agent=message.source_agent,
                message_type=MessageType.STATUS_RESPONSE,
                payload=self.get_status(),
                correlation_id=message.correlation_id,
            )
        logger.debug("ExecutorAgent processing %s from %s", message.message_type.value, message.source_agent)
        return None

    def get_role(self) -> str:
        return "executor"

    def get_authority(self) -> AuthorityLevel:
        return AuthorityLevel.EXECUTION


class HistorianAgent(BaseAgent):
    """Knowledge graph management, pattern storage, trade forensics."""

    async def handle_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        self._message_log.append(message)
        if message.message_type == MessageType.STATUS_REQUEST:
            return AgentMessage(
                source_agent=self.get_role(),
                target_agent=message.source_agent,
                message_type=MessageType.STATUS_RESPONSE,
                payload=self.get_status(),
                correlation_id=message.correlation_id,
            )
        logger.debug("HistorianAgent processing %s from %s", message.message_type.value, message.source_agent)
        return None

    def get_role(self) -> str:
        return "historian"

    def get_authority(self) -> AuthorityLevel:
        return AuthorityLevel.ADVISORY


class EvolverAgent(BaseAgent):
    """Genome evolution, fitness evaluation, population management."""

    async def handle_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        self._message_log.append(message)
        if message.message_type == MessageType.STATUS_REQUEST:
            return AgentMessage(
                source_agent=self.get_role(),
                target_agent=message.source_agent,
                message_type=MessageType.STATUS_RESPONSE,
                payload=self.get_status(),
                correlation_id=message.correlation_id,
            )
        logger.debug("EvolverAgent processing %s from %s", message.message_type.value, message.source_agent)
        return None

    def get_role(self) -> str:
        return "evolver"

    def get_authority(self) -> AuthorityLevel:
        return AuthorityLevel.ADVISORY


# ---------------------------------------------------------------------------
# Message bus
# ---------------------------------------------------------------------------

class MessageBus:
    """In-process typed message router for the agent council.

    Agents register with the bus.  Messages are routed by target_agent
    (direct) or broadcast to all registered agents.
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._history: list[AgentMessage] = []
        self._interceptors: list[Callable[[AgentMessage], Optional[AgentMessage]]] = []

    def register(self, agent: BaseAgent) -> None:
        role = agent.get_role()
        if role in self._agents:
            raise ValueError(f"Agent with role '{role}' already registered")
        self._agents[role] = agent
        logger.info("MessageBus: registered agent '%s'", role)

    def unregister(self, role: str) -> None:
        self._agents.pop(role, None)

    def add_interceptor(self, fn: Callable[[AgentMessage], Optional[AgentMessage]]) -> None:
        """Add a message interceptor (e.g., for logging, authority checks)."""
        self._interceptors.append(fn)

    def get_agent(self, role: str) -> Optional[BaseAgent]:
        return self._agents.get(role)

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())

    async def dispatch(self, message: AgentMessage) -> list[AgentMessage]:
        """Route a message and collect responses.

        Returns a list of response messages from handling agents.
        """
        self._history.append(message)
        set_council_queue_depth(len(self._history))

        # Run interceptors (any can transform or suppress the message)
        for interceptor in self._interceptors:
            result = interceptor(message)
            if result is None:
                return []  # suppressed
            message = result

        responses: list[AgentMessage] = []

        if message.target_agent == "broadcast":
            for agent in self._agents.values():
                if agent.can_handle(message):
                    t0 = time.monotonic()
                    resp = await agent.handle_message(message)
                    elapsed = time.monotonic() - t0
                    record_council_response_time(agent.get_role(), elapsed)
                    record_council_message(
                        message.source_agent, message.target_agent,
                        message.message_type.value,
                    )
                    if resp is not None:
                        responses.append(resp)
        else:
            agent = self._agents.get(message.target_agent)
            if agent and agent.can_handle(message):
                t0 = time.monotonic()
                resp = await agent.handle_message(message)
                elapsed = time.monotonic() - t0
                record_council_response_time(agent.get_role(), elapsed)
                record_council_message(
                    message.source_agent, message.target_agent,
                    message.message_type.value,
                )
                if resp is not None:
                    responses.append(resp)

        return responses

    def get_history(self, limit: int = 100) -> list[AgentMessage]:
        return self._history[-limit:]


# ---------------------------------------------------------------------------
# Authority hierarchy
# ---------------------------------------------------------------------------

class AuthorityHierarchy:
    """Enforces the agent authority chain from ADR-012.

    Hierarchy (top = highest authority):
        RiskManager (external, non-bypassable)
            -> CriticAgent   (veto)
                -> ExecutorAgent (execution)
                    -> all others (advisory)

    The CriticAgent can veto execution proposals.
    Only the ExecutorAgent can issue EXECUTION_ORDER messages.
    Advisory agents cannot issue EXECUTION_ORDER or CRITIQUE messages.
    """

    # Map authority level to numeric rank (higher = more authority)
    _RANK: dict[AuthorityLevel, int] = {
        AuthorityLevel.ADVISORY: 0,
        AuthorityLevel.EXECUTION: 1,
        AuthorityLevel.VETO: 2,
    }

    # Which message types each authority level may emit
    _ALLOWED_EMIT: dict[AuthorityLevel, set[MessageType]] = {
        AuthorityLevel.ADVISORY: {MessageType.SIGNAL, MessageType.PROPOSAL, MessageType.LESSON, MessageType.EVOLUTION_REQUEST, MessageType.STATUS_REQUEST, MessageType.STATUS_RESPONSE},
        AuthorityLevel.EXECUTION: {MessageType.EXECUTION_ORDER, MessageType.SIGNAL, MessageType.PROPOSAL, MessageType.STATUS_REQUEST, MessageType.STATUS_RESPONSE},
        AuthorityLevel.VETO: {MessageType.CRITIQUE, MessageType.SIGNAL, MessageType.PROPOSAL, MessageType.STATUS_REQUEST, MessageType.STATUS_RESPONSE},
    }

    def can_emit(self, agent: BaseAgent, message_type: MessageType) -> bool:
        """Check whether the agent's authority permits emitting this message type."""
        allowed = self._ALLOWED_EMIT.get(agent.get_authority(), set())
        return message_type in allowed

    def has_higher_authority(self, agent_a: BaseAgent, agent_b: BaseAgent) -> bool:
        """Return True if agent_a outranks agent_b."""
        return self._RANK.get(agent_a.get_authority(), 0) > self._RANK.get(agent_b.get_authority(), 0)

    def can_veto(self, agent: BaseAgent) -> bool:
        """Return True if the agent has veto authority."""
        return agent.get_authority() == AuthorityLevel.VETO

    def validate_dispatch(self, message: AgentMessage, source_agent: BaseAgent) -> bool:
        """Validate that the source agent is allowed to send this message type."""
        return self.can_emit(source_agent, message.message_type)


# ---------------------------------------------------------------------------
# Agent council orchestrator
# ---------------------------------------------------------------------------

class AgentCouncil:
    """Orchestrates agent message flow and lifecycle.

    Phases (per ADR-012):
        1. Broadcast — Analyst + Historian run concurrently
        2. Synthesis — Synthesizer receives signals + lessons
        3. Critique  — Critic validates proposals
        4. Execution — Executor acts on approved proposals
        5. Evolution — Evolver updates genomes
    """

    _DEFAULT_ROLES = ("analyst", "synthesizer", "critic", "executor", "historian", "evolver")

    def __init__(self) -> None:
        self.bus = MessageBus()
        self.authority = AuthorityHierarchy()
        self._started = False

    def register_default_agents(self) -> None:
        """Register all 6 default agents."""
        self.bus.register(AnalystAgent())
        self.bus.register(SynthesizerAgent())
        self.bus.register(CriticAgent())
        self.bus.register(ExecutorAgent())
        self.bus.register(HistorianAgent())
        self.bus.register(EvolverAgent())

    def register_agent(self, agent: BaseAgent) -> None:
        """Register a custom agent."""
        self.bus.register(agent)

    def start(self) -> None:
        """Mark council as started; install authority interceptor."""
        self.bus.add_interceptor(self._authority_interceptor)
        self._started = True
        logger.info("AgentCouncil started with %d agents", len(self.bus.list_agents()))

    def stop(self) -> None:
        self._started = False
        logger.info("AgentCouncil stopped")

    @property
    def is_started(self) -> bool:
        return self._started

    def _authority_interceptor(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Interceptor that enforces authority hierarchy on dispatched messages."""
        source = self.bus.get_agent(message.source_agent)
        if source is None:
            return message  # allow external/system messages through
        if not self.authority.can_emit(source, message.message_type):
            record_council_authority_rejection(
                message.source_agent, message.message_type.value,
            )
            logger.warning(
                "AuthorityHierarchy: agent '%s' (authority=%s) cannot emit %s — suppressed",
                source.get_role(),
                source.get_authority().value,
                message.message_type.value,
            )
            return None
        return message

    async def run_phase(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        """Dispatch a list of messages through the bus and collect all responses."""
        all_responses: list[AgentMessage] = []
        for msg in messages:
            responses = await self.bus.dispatch(msg)
            all_responses.extend(responses)
        return all_responses

    def get_agent_status(self) -> dict[str, Any]:
        """Return status of all registered agents."""
        result: dict[str, Any] = {}
        for role in self.bus.list_agents():
            agent = self.bus.get_agent(role)
            if agent:
                result[role] = agent.get_status()
        return result
