"""Tests for backend/ai/llm_router.py — LLMRouter provider routing and JSON parsing."""

import json
import pytest
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Helpers: build an LLMRouter with fake provider configs (no real API keys)
# ---------------------------------------------------------------------------


def _make_router(providers=None, default="groq"):
    """Instantiate LLMRouter without touching real settings."""
    with patch("backend.ai.llm_router.LLMRouter.__init__", lambda self: None):
        from backend.ai.llm_router import LLMRouter

        router = LLMRouter()
        router.providers = providers or {}
        router.default_provider = default
        return router


GROQ_CFG = {
    "api_key": "fake-groq-key",
    "model": "llama3-70b-8192",
    "base_url": None,
    "max_tokens": 250,
    "temperature": 0.2,
}

CLAUDE_CFG = {
    "api_key": "fake-claude-key",
    "model": "claude-sonnet-4-20250514",
    "base_url": None,
    "max_tokens": 300,
    "temperature": 0.2,
}


# ---------------------------------------------------------------------------
# ROLE_SETTING_MAP / _resolve_provider
# ---------------------------------------------------------------------------


class TestResolveProvider:
    def test_default_role_returns_default_provider(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        with patch("backend.ai.llm_router.settings") as mock_settings:
            mock_settings.LLM_DEFAULT_PROVIDER = "groq"
            result = router._resolve_provider("default")
        assert result == "groq"

    def test_claude_escalation_with_claude_available(self):
        router = _make_router({"groq": GROQ_CFG, "claude": CLAUDE_CFG}, default="groq")
        result = router._resolve_provider("claude_escalation")
        assert result == "claude"

    def test_claude_escalation_without_claude_falls_back(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        result = router._resolve_provider("claude_escalation")
        assert result == "groq"

    def test_unknown_role_returns_default(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        result = router._resolve_provider("nonexistent_role")
        assert result == "groq"

    def test_debate_agent_role_resolves_from_settings(self):
        router = _make_router({"groq": GROQ_CFG, "claude": CLAUDE_CFG}, default="groq")
        with patch("backend.ai.llm_router.settings") as mock_settings:
            mock_settings.LLM_DEBATE_PROVIDER = "claude"
            result = router._resolve_provider("debate_agent")
        assert result == "claude"

    def test_debate_agent_role_invalid_provider_falls_back(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        with patch("backend.ai.llm_router.settings") as mock_settings:
            mock_settings.LLM_DEBATE_PROVIDER = "missing_provider"
            result = router._resolve_provider("debate_agent")
        assert result == "groq"


# ---------------------------------------------------------------------------
# _fallback_order
# ---------------------------------------------------------------------------


class TestFallbackOrder:
    def test_primary_is_first(self):
        router = _make_router({"groq": GROQ_CFG, "claude": CLAUDE_CFG})
        order = router._fallback_order("groq")
        assert order[0] == "groq"
        assert "claude" in order

    def test_primary_not_duplicated(self):
        router = _make_router({"groq": GROQ_CFG, "claude": CLAUDE_CFG})
        order = router._fallback_order("claude")
        assert order.count("claude") == 1
        assert order[0] == "claude"

    def test_single_provider(self):
        router = _make_router({"groq": GROQ_CFG})
        order = router._fallback_order("groq")
        assert order == ["groq"]


# ---------------------------------------------------------------------------
# _dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_groq_calls_call_groq(self):
        router = _make_router({"groq": GROQ_CFG})
        router._call_groq = AsyncMock(return_value=("response text", 42))
        messages = [{"role": "user", "content": "test"}]
        text, tokens = await router._dispatch("groq", GROQ_CFG, messages)
        assert text == "response text"
        assert tokens == 42
        router._call_groq.assert_awaited_once_with(GROQ_CFG, messages)

    @pytest.mark.asyncio
    async def test_dispatch_claude_calls_call_claude(self):
        router = _make_router({"claude": CLAUDE_CFG})
        router._call_claude = AsyncMock(return_value=("claude reply", 100))
        messages = [{"role": "user", "content": "test"}]
        text, tokens = await router._dispatch("claude", CLAUDE_CFG, messages)
        assert text == "claude reply"
        assert tokens == 100

    @pytest.mark.asyncio
    async def test_dispatch_unknown_provider_raises(self):
        router = _make_router({})
        with pytest.raises(ValueError, match="Unknown provider"):
            await router._dispatch("nonexistent_provider_xyz", {}, [])


# ---------------------------------------------------------------------------
# complete — mocks _dispatch to avoid real API calls
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_returns_text_on_success(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        router._dispatch = AsyncMock(return_value=("Hello world", 10))
        result = await router.complete("Say hello")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_complete_builds_messages_with_system(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        captured = {}

        async def _capture(provider_name, config, messages, **kw):
            captured["messages"] = messages
            return ("ok", 5)

        router._dispatch = _capture
        await router.complete("my prompt", system="be helpful")
        assert len(captured["messages"]) == 2
        assert captured["messages"][0]["role"] == "system"
        assert captured["messages"][0]["content"] == "be helpful"
        assert captured["messages"][1]["role"] == "user"
        assert captured["messages"][1]["content"] == "my prompt"

    @pytest.mark.asyncio
    async def test_complete_builds_messages_without_system(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        captured = {}

        async def _capture(provider_name, config, messages, **kw):
            captured["messages"] = messages
            return ("ok", 5)

        router._dispatch = _capture
        await router.complete("my prompt")
        assert len(captured["messages"]) == 1
        assert captured["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_complete_fallback_on_primary_failure(self):
        router = _make_router({"groq": GROQ_CFG, "claude": CLAUDE_CFG}, default="groq")
        call_count = {"n": 0}

        async def _fail_then_succeed(provider_name, config, messages, **kw):
            call_count["n"] += 1
            if provider_name == "groq":
                raise ConnectionError("Groq down")
            return ("claude backup", 20)

        router._dispatch = _fail_then_succeed
        result = await router.complete("test fallback")
        assert result == "claude backup"
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_complete_all_fail_returns_empty(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")

        async def _always_fail(provider_name, config, messages, **kw):
            raise RuntimeError("fail")

        router._dispatch = _always_fail
        result = await router.complete("test all fail")
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_no_providers_returns_empty(self):
        router = _make_router({}, default="groq")
        result = await router.complete("no providers")
        assert result == ""


# ---------------------------------------------------------------------------
# complete_json — JSON extraction from raw LLM text
# ---------------------------------------------------------------------------


class TestCompleteJson:
    @pytest.mark.asyncio
    async def test_complete_json_valid_json(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        data = {"probability": 0.72, "confidence": 0.85}
        router._dispatch = AsyncMock(return_value=(json.dumps(data), 10))
        result = await router.complete_json("test")
        assert result["probability"] == pytest.approx(0.72)
        assert result["confidence"] == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_complete_json_embedded_in_prose(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        data = {"answer": 42}
        raw = f"Here is my analysis: {json.dumps(data)} Hope that helps."
        router._dispatch = AsyncMock(return_value=(raw, 15))
        result = await router.complete_json("test")
        assert result["answer"] == 42

    @pytest.mark.asyncio
    async def test_complete_json_no_json_returns_empty_dict(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        router._dispatch = AsyncMock(return_value=("no json here", 5))
        result = await router.complete_json("test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_complete_json_malformed_json_returns_empty_dict(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        router._dispatch = AsyncMock(return_value=('{"broken": ', 5))
        result = await router.complete_json("test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_complete_json_empty_response_returns_empty_dict(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        router._dispatch = AsyncMock(return_value=("", 0))
        result = await router.complete_json("test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_complete_json_all_providers_fail_returns_empty_dict(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")

        async def _fail(provider_name, config, messages, **kw):
            raise RuntimeError("fail")

        router._dispatch = _fail
        result = await router.complete_json("test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_complete_json_nested_object(self):
        router = _make_router({"groq": GROQ_CFG}, default="groq")
        data = {
            "signal": {"direction": "buy", "confidence": 0.9},
            "reasoning": "strong",
        }
        router._dispatch = AsyncMock(return_value=(json.dumps(data), 20))
        result = await router.complete_json("test")
        assert result["signal"]["direction"] == "buy"
        assert result["signal"]["confidence"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_complete_json_with_role_kwarg(self):
        router = _make_router({"groq": GROQ_CFG, "claude": CLAUDE_CFG}, default="groq")
        data = {"result": "ok"}
        router._dispatch = AsyncMock(return_value=(json.dumps(data), 5))
        result = await router.complete_json("test", role="claude_escalation")
        assert result["result"] == "ok"
