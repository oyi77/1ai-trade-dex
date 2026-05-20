"""Tests for the Multi-Agent Council (ADR-012).

Covers:
    - Message routing via MessageBus (direct + broadcast)
    - Authority hierarchy enforcement
    - Agent lifecycle (can_handle, get_status)
    - AgentCouncil orchestration
"""

from __future__ import annotations

import pytest

from backend.core.agent_council import (
    AgentCouncil,
    AgentMessage,
    AnalystAgent,
    AuthorityHierarchy,
    AuthorityLevel,
    BaseAgent,
    CriticAgent,
    EvolverAgent,
    ExecutorAgent,
    HistorianAgent,
    MessageBus,
    MessageType,
    SynthesizerAgent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    source: str = "analyst",
    target: str = "broadcast",
    msg_type: MessageType = MessageType.SIGNAL,
    payload: dict | None = None,
    correlation_id: str = "test-corr-001",
) -> AgentMessage:
    return AgentMessage(
        source_agent=source,
        target_agent=target,
        message_type=msg_type,
        payload=payload or {"data": "test"},
        correlation_id=correlation_id,
    )


class EchoAgent(BaseAgent):
    """Test agent that echoes back every message it receives."""

    def __init__(
        self, role: str = "echo", authority: AuthorityLevel = AuthorityLevel.ADVISORY
    ):
        super().__init__()
        self._role = role
        self._authority = authority

    async def handle_message(self, message: AgentMessage) -> AgentMessage | None:
        self._message_log.append(message)
        return AgentMessage(
            source_agent=self._role,
            target_agent=message.source_agent,
            message_type=MessageType.SIGNAL,
            payload={"echo": message.payload, "from": self._role},
            correlation_id=message.correlation_id,
        )

    def get_role(self) -> str:
        return self._role

    def get_authority(self) -> AuthorityLevel:
        return self._authority


class SilentAgent(BaseAgent):
    """Test agent that never responds."""

    async def handle_message(self, message: AgentMessage) -> None:
        self._message_log.append(message)
        return None

    def get_role(self) -> str:
        return "silent"

    def get_authority(self) -> AuthorityLevel:
        return AuthorityLevel.ADVISORY


# ---------------------------------------------------------------------------
# MessageBus tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_direct_dispatch():
    bus = MessageBus()
    echo = EchoAgent()
    bus.register(echo)

    msg = _make_message(target="echo")
    responses = await bus.dispatch(msg)
    assert len(responses) == 1
    assert responses[0].payload["from"] == "echo"


@pytest.mark.asyncio
async def test_bus_broadcast_dispatch():
    bus = MessageBus()
    bus.register(EchoAgent("a1"))
    bus.register(EchoAgent("a2"))
    bus.register(SilentAgent())

    msg = _make_message(target="broadcast")
    responses = await bus.dispatch(msg)
    # two echo agents respond, silent does not
    assert len(responses) == 2
    responding_roles = {r.source_agent for r in responses}
    assert responding_roles == {"a1", "a2"}


@pytest.mark.asyncio
async def test_bus_expired_message_not_delivered():
    bus = MessageBus()
    echo = EchoAgent()
    bus.register(echo)

    msg = _make_message(target="echo", msg_type=MessageType.SIGNAL)
    # Force expiry by setting ttl to 0 and waiting
    msg.ttl_seconds = 0
    import time

    time.sleep(0.01)
    responses = await bus.dispatch(msg)
    assert len(responses) == 0


@pytest.mark.asyncio
async def test_bus_no_route_for_unknown_target():
    bus = MessageBus()
    bus.register(EchoAgent())

    msg = _make_message(target="nonexistent")
    responses = await bus.dispatch(msg)
    assert len(responses) == 0


def test_bus_register_duplicate_raises():
    bus = MessageBus()
    bus.register(EchoAgent("dup"))
    with pytest.raises(ValueError, match="already registered"):
        bus.register(EchoAgent("dup"))


def test_bus_unregister():
    bus = MessageBus()
    bus.register(EchoAgent("temp"))
    assert "temp" in bus.list_agents()
    bus.unregister("temp")
    assert "temp" not in bus.list_agents()


@pytest.mark.asyncio
async def test_bus_interceptor_can_suppress():
    bus = MessageBus()
    bus.register(EchoAgent())
    bus.add_interceptor(lambda msg: None)  # suppress all

    responses = await bus.dispatch(_make_message(target="echo"))
    assert len(responses) == 0


@pytest.mark.asyncio
async def test_bus_history():
    bus = MessageBus()
    bus.register(EchoAgent())
    await bus.dispatch(_make_message(target="echo"))
    history = bus.get_history()
    assert len(history) == 1
    assert history[0].source_agent == "analyst"


# ---------------------------------------------------------------------------
# Authority hierarchy tests
# ---------------------------------------------------------------------------


def test_authority_advisory_cannot_emit_execution_order():
    hierarchy = AuthorityHierarchy()
    agent = AnalystAgent()
    assert hierarchy.can_emit(agent, MessageType.EXECUTION_ORDER) is False


def test_authority_advisory_can_emit_signal():
    hierarchy = AuthorityHierarchy()
    agent = AnalystAgent()
    assert hierarchy.can_emit(agent, MessageType.SIGNAL) is True


def test_authority_executor_can_emit_execution_order():
    hierarchy = AuthorityHierarchy()
    agent = ExecutorAgent()
    assert hierarchy.can_emit(agent, MessageType.EXECUTION_ORDER) is True


def test_authority_executor_cannot_emit_critique():
    hierarchy = AuthorityHierarchy()
    agent = ExecutorAgent()
    assert hierarchy.can_emit(agent, MessageType.CRITIQUE) is False


def test_authority_critic_can_emit_critique():
    hierarchy = AuthorityHierarchy()
    agent = CriticAgent()
    assert hierarchy.can_emit(agent, MessageType.CRITIQUE) is True


def test_authority_critic_has_veto():
    hierarchy = AuthorityHierarchy()
    agent = CriticAgent()
    assert hierarchy.can_veto(agent) is True


def test_authority_non_critic_no_veto():
    hierarchy = AuthorityHierarchy()
    for agent_cls in (
        AnalystAgent,
        SynthesizerAgent,
        ExecutorAgent,
        HistorianAgent,
        EvolverAgent,
    ):
        assert hierarchy.can_veto(agent_cls()) is False


def test_authority_critic_outranks_executor():
    hierarchy = AuthorityHierarchy()
    critic = CriticAgent()
    executor = ExecutorAgent()
    assert hierarchy.has_higher_authority(critic, executor) is True
    assert hierarchy.has_higher_authority(executor, critic) is False


def test_authority_executor_outranks_advisory():
    hierarchy = AuthorityHierarchy()
    executor = ExecutorAgent()
    for agent_cls in (AnalystAgent, SynthesizerAgent, HistorianAgent, EvolverAgent):
        assert hierarchy.has_higher_authority(executor, agent_cls()) is True


def test_authority_validate_dispatch():
    hierarchy = AuthorityHierarchy()
    analyst = AnalystAgent()
    executor = ExecutorAgent()
    msg_signal = _make_message(source="analyst", msg_type=MessageType.SIGNAL)
    msg_exec = _make_message(source="executor", msg_type=MessageType.EXECUTION_ORDER)
    msg_bad = _make_message(source="analyst", msg_type=MessageType.EXECUTION_ORDER)

    assert hierarchy.validate_dispatch(msg_signal, analyst) is True
    assert hierarchy.validate_dispatch(msg_exec, executor) is True
    assert hierarchy.validate_dispatch(msg_bad, analyst) is False


# ---------------------------------------------------------------------------
# Agent can_handle / get_status tests
# ---------------------------------------------------------------------------


def test_can_handle_broadcast():
    agent = AnalystAgent()
    msg = _make_message(target="broadcast")
    assert agent.can_handle(msg) is True


def test_can_handle_directed():
    agent = AnalystAgent()
    msg = _make_message(target="analyst")
    assert agent.can_handle(msg) is True


def test_can_handle_wrong_target():
    agent = AnalystAgent()
    msg = _make_message(target="executor")
    assert agent.can_handle(msg) is False


def test_get_status_structure():
    agent = CriticAgent()
    status = agent.get_status()
    assert status["role"] == "critic"
    assert status["authority"] == "veto"
    assert status["messages_processed"] == 0


@pytest.mark.asyncio
async def test_status_request_response():
    agent = HistorianAgent()
    req = _make_message(target="historian", msg_type=MessageType.STATUS_REQUEST)
    resp = await agent.handle_message(req)
    assert resp is not None
    assert resp.message_type == MessageType.STATUS_RESPONSE
    assert resp.payload["role"] == "historian"


# ---------------------------------------------------------------------------
# AgentCouncil integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_council_register_and_start():
    council = AgentCouncil()
    council.register_default_agents()
    assert set(council.bus.list_agents()) == {
        "analyst",
        "synthesizer",
        "critic",
        "executor",
        "historian",
        "evolver",
    }
    council.start()
    assert council.is_started is True
    council.stop()
    assert council.is_started is False


@pytest.mark.asyncio
async def test_council_authority_blocks_illegal_message():
    council = AgentCouncil()
    council.register_default_agents()
    council.start()

    # Analyst tries to emit EXECUTION_ORDER — should be suppressed by interceptor
    msg = _make_message(
        source="analyst", target="broadcast", msg_type=MessageType.EXECUTION_ORDER
    )
    responses = await council.bus.dispatch(msg)
    # No agent should receive it because the interceptor suppresses it
    assert len(responses) == 0


@pytest.mark.asyncio
async def test_council_allows_legal_message():
    council = AgentCouncil()
    council.register_default_agents()
    council.start()

    # Analyst emits a SIGNAL — allowed
    msg = _make_message(
        source="analyst", target="broadcast", msg_type=MessageType.SIGNAL
    )
    responses = await council.bus.dispatch(msg)
    # STATUS_REQUEST handling aside, broadcast SIGNAL should reach all agents
    # (agents just log and return None for plain SIGNAL)
    # No responses expected since default agents return None for SIGNAL
    assert len(responses) == 0


@pytest.mark.asyncio
async def test_council_run_phase():
    council = AgentCouncil()
    council.register_agent(EchoAgent("e1"))
    council.register_agent(EchoAgent("e2"))
    council.start()

    messages = [
        _make_message(target="e1", msg_type=MessageType.SIGNAL),
        _make_message(target="e2", msg_type=MessageType.SIGNAL),
    ]
    responses = await council.run_phase(messages)
    assert len(responses) == 2


def test_council_get_agent_status():
    council = AgentCouncil()
    council.register_default_agents()
    status = council.get_agent_status()
    assert len(status) == 6
    assert "analyst" in status
    assert "critic" in status
    assert status["critic"]["authority"] == "veto"


# ---------------------------------------------------------------------------
# Agent role and authority identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_cls,expected_role,expected_authority",
    [
        (AnalystAgent, "analyst", AuthorityLevel.ADVISORY),
        (SynthesizerAgent, "synthesizer", AuthorityLevel.ADVISORY),
        (CriticAgent, "critic", AuthorityLevel.VETO),
        (ExecutorAgent, "executor", AuthorityLevel.EXECUTION),
        (HistorianAgent, "historian", AuthorityLevel.ADVISORY),
        (EvolverAgent, "evolver", AuthorityLevel.ADVISORY),
    ],
)
def test_agent_identity(agent_cls, expected_role, expected_authority):
    agent = agent_cls()
    assert agent.get_role() == expected_role
    assert agent.get_authority() == expected_authority


# ---------------------------------------------------------------------------
# Message protocol tests
# ---------------------------------------------------------------------------


def test_message_is_expired():
    msg = _make_message()
    msg.ttl_seconds = 0
    import time

    time.sleep(0.01)
    assert msg.is_expired() is True


def test_message_not_expired():
    msg = _make_message()
    msg.ttl_seconds = 300
    assert msg.is_expired() is False


def test_message_to_dict():
    msg = _make_message()
    d = msg.to_dict()
    assert d["source_agent"] == "analyst"
    assert d["message_type"] == "signal"
    assert "correlation_id" in d
    assert "timestamp" in d
