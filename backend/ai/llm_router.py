"""Unified LLM provider routing layer.

Supports: groq, claude, openai-compatible (any provider with OpenAI API).
Configurable via settings.LLM_PROVIDERS JSON dict or individual ENV vars.
Single source of truth for all AI provider management.
"""

import json
import os
from typing import Optional

from loguru import logger
from backend.config import settings
from backend.core.llm_cost_tracker import LLMCostTracker

try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

# Approximate cost per 1K tokens by provider type (USD)
_PROVIDER_COST_PER_1K: dict[str, float] = {
    "groq": 0.0002,
    "claude": 0.015,
    "openai": 0.005,
    "together": 0.002,
    "fireworks": 0.002,
    "ollama": 0.0,
    "custom": 0.002,
}

ROLE_SETTING_MAP = {
    "default": "LLM_DEFAULT_PROVIDER",
    "debate_agent": "LLM_DEBATE_PROVIDER",
    "judge": "LLM_JUDGE_PROVIDER",
    "claude_escalation": "claude",
}

# Single definition per provider: env key + runtime defaults + display metadata
_BUILTIN_PROVIDERS: list[dict] = [
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "model_default": "llama-3.3-70b-versatile",
        "max_tokens": 250,
        "temperature": 0.2,
        "provider_type": "groq",
        "display_name": "Groq",
        "tags": ["primary", "llm", "fast"],
        "cost_per_1k_tokens_usd": 0.0005,
        "supports_streaming": False,
        "supports_tool_use": False,
    },
    {
        "name": "claude",
        "env_key": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
        "model_default": "claude-sonnet-4-20250514",
        "max_tokens": 300,
        "temperature": 0.2,
        "provider_type": "claude",
        "display_name": "Anthropic Claude",
        "tags": ["primary", "llm", "reasoning"],
        "cost_per_1k_tokens_usd": 0.003,
        "supports_streaming": False,
        "supports_tool_use": True,
    },
    {
        "name": "openai",
        "env_key": "LLM_OPENAI_API_KEY",
        "model_env": "LLM_OPENAI_MODEL",
        "model_default": "gpt-4o-mini",
        "max_tokens": 250,
        "temperature": 0.2,
        "provider_type": "openai",
        "display_name": "OpenAI",
        "tags": ["openai-compat", "llm"],
        "cost_per_1k_tokens_usd": 0.005,
        "supports_streaming": True,
        "supports_tool_use": True,
    },
    {
        "name": "gemini",
        "env_key": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "model_default": "gemini-1.5-pro",
        "max_tokens": 250,
        "temperature": 0.2,
        "provider_type": "openai",
        "display_name": "Google Gemini",
        "tags": ["google", "mid-tier"],
        "cost_per_1k_tokens_usd": 0.001,
        "supports_streaming": False,
        "supports_tool_use": False,
    },
    {
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "model_default": "openai/gpt-4o-mini",
        "max_tokens": 250,
        "temperature": 0.2,
        "provider_type": "openai",
        "display_name": "OpenRouter",
        "tags": ["aggregator", "multi-model"],
        "cost_per_1k_tokens_usd": 0.001,
        "supports_streaming": True,
        "supports_tool_use": True,
    },
]


def _build_openai_provider(name: str, cfg: dict) -> dict:
    """Build a provider config dict from a raw settings entry."""
    return {
        "provider_type": "openai",
        "api_key": cfg.get("api_key", ""),
        "model": cfg.get("model", "gpt-4o-mini"),
        "base_url": cfg.get("base_url") or None,
        "max_tokens": int(cfg.get("max_tokens", 250)),
        "temperature": float(cfg.get("temperature", 0.2)),
        "display_name": cfg.get("display_name", name.title()),
        "tags": cfg.get("tags", []),
        "cost_per_1k_tokens_usd": float(cfg.get("cost_per_1k_tokens_usd", 0.002)),
        "supports_streaming": cfg.get("supports_streaming", True),
        "supports_tool_use": cfg.get("supports_tool_use", True),
    }


def _discover_providers() -> dict[str, dict]:
    """Build runtime provider configs from settings + env vars.
    Each entry carries runtime config + display metadata inline.
    """

    providers: dict[str, dict] = {}

    for defn in _BUILTIN_PROVIDERS:
        name = defn["name"]
        env_key = defn["env_key"]
        api_key = os.getenv(env_key) or getattr(settings, env_key, None) or ""
        if not api_key:
            continue

        providers[name] = {
            "api_key": api_key,
            "model": getattr(settings, defn["model_env"], defn["model_default"]),
            "base_url": None,
            "max_tokens": defn["max_tokens"],
            "temperature": defn["temperature"],
            "provider_type": defn["provider_type"],
            "display_name": defn["display_name"],
            "tags": defn.get("tags", []),
            "cost_per_1k_tokens_usd": defn.get("cost_per_1k_tokens_usd", 0.0),
            "supports_streaming": defn.get("supports_streaming", False),
            "supports_tool_use": defn.get("supports_tool_use", False),
        }

    # Configurable: LLM_PROVIDERS JSON dict (e.g. together, fireworks, ollama)
    raw_providers = getattr(settings, "LLM_PROVIDERS", None)
    if raw_providers:
        try:
            if isinstance(raw_providers, str):
                raw_providers = json.loads(raw_providers)
            for name, cfg in raw_providers.items():
                if name in providers:
                    continue
                providers[name] = _build_openai_provider(name, cfg)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("LLMRouter: failed to parse LLM_PROVIDERS: {}", e)

    return providers


class LLMRouter:
    def __init__(self):

        self.providers: dict[str, dict] = _discover_providers()
        self.default_provider: str = getattr(settings, "LLM_DEFAULT_PROVIDER", "groq")
        if self.default_provider not in self.providers and self.providers:
            self.default_provider = next(iter(self.providers))
        self._cost_tracker = LLMCostTracker()

    def _resolve_provider(self, role: str) -> Optional[str]:

        mapping = ROLE_SETTING_MAP.get(role)
        if mapping is None:
            return self.default_provider

        if mapping == "claude":
            return "claude" if "claude" in self.providers else self.default_provider

        provider_name = getattr(settings, mapping, self.default_provider)
        return (
            provider_name if provider_name in self.providers else self.default_provider
        )

    def _fallback_order(self, primary: str) -> list[str]:
        return [primary] + [p for p in self.providers if p != primary]

    async def _call_groq(
        self, config: dict, messages: list[dict], **kwargs
    ) -> tuple[str, int]:

        client = AsyncGroq(api_key=config["api_key"])
        response = await client.chat.completions.create(
            model=kwargs.get("model", config["model"]),
            messages=messages,
            max_tokens=kwargs.get("max_tokens", config["max_tokens"]),
            temperature=kwargs.get("temperature", config["temperature"]),
        )
        text = response.choices[0].message.content.strip()
        tokens = response.usage.total_tokens if response.usage else 0
        return text, tokens

    async def _call_claude(
        self, config: dict, messages: list[dict], **kwargs
    ) -> tuple[str, int]:

        client = AsyncAnthropic(api_key=config["api_key"])

        system_msg = None
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        create_kwargs: dict = {
            "model": kwargs.get("model", config["model"]),
            "max_tokens": kwargs.get("max_tokens", config["max_tokens"]),
            "messages": user_messages or [{"role": "user", "content": ""}],
        }
        if system_msg:
            create_kwargs["system"] = system_msg

        response = await client.messages.create(**create_kwargs)
        text = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens
        return text, tokens

    async def _call_openai(
        self, config: dict, messages: list[dict], **kwargs
    ) -> tuple[str, int]:

        base = config.get("base_url") or None
        client = AsyncOpenAI(api_key=config["api_key"], base_url=base)
        create_kwargs = dict(
            model=kwargs.get("model", config["model"]),
            messages=messages,
            max_tokens=kwargs.get("max_tokens", config["max_tokens"]),
            temperature=kwargs.get("temperature", config["temperature"]),
        )
        if "response_format" in kwargs:
            create_kwargs["response_format"] = kwargs["response_format"]
        response = await client.chat.completions.create(**create_kwargs)
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return text.strip(), tokens

    async def _dispatch(
        self, provider_name: str, config: dict, messages: list[dict], **kwargs
    ) -> tuple[str, int]:
        ptype = config.get("provider_type", provider_name)
        if ptype in ("openai", "together", "fireworks", "ollama", "custom"):
            return await self._call_openai(config, messages, **kwargs)
        if ptype == "groq":
            return await self._call_groq(config, messages, **kwargs)
        if ptype == "claude":
            return await self._call_claude(config, messages, **kwargs)
        raise ValueError(f"Unknown provider: {provider_name} (type={ptype})")

    async def complete(
        self,
        prompt: str,
        role: str = "default",
        system: Optional[str] = None,
        **kwargs,
    ) -> str:
        primary = self._resolve_provider(role)
        if primary is None or primary not in self.providers:
            logger.error("No LLM provider configured")
            return ""

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Lazy-init cost tracker (may be absent if __init__ was patched in tests)
        cost_tracker = getattr(self, "_cost_tracker", None)
        if cost_tracker is None:

            cost_tracker = LLMCostTracker()
            self._cost_tracker = cost_tracker

        last_error: Optional[Exception] = None
        for provider_name in self._fallback_order(primary):
            config = self.providers[provider_name]
            # Estimate cost before calling
            est_cost_per_1k = _PROVIDER_COST_PER_1K.get(
                config.get("provider_type", provider_name), 0.002
            )
            est_cost = est_cost_per_1k * (config.get("max_tokens", 250) + 500) / 1000
            if not cost_tracker.can_spend(est_cost):
                logger.warning(
                    f"LLMRouter: daily budget exhausted, skipping {provider_name}"
                )
                continue
            try:
                text, tokens = await self._dispatch(
                    provider_name, config, messages, **kwargs
                )
                actual_cost = est_cost_per_1k * max(tokens, 1) / 1000
                try:
                    cost_tracker.record_call(
                        model=config.get("model", provider_name),
                        token_count=tokens,
                        cost_usd=actual_cost,
                        purpose=role,
                    )
                except Exception as ct_err:
                    logger.warning(f"LLMRouter: cost tracking failed: {ct_err}")
                return text
            except Exception as e:
                logger.warning(f"LLMRouter: {provider_name} failed: {e}")
                last_error = e

        logger.error(f"All LLM providers failed. Last error: {last_error}")
        return ""

    async def complete_json(
        self,
        prompt: str,
        role: str = "default",
        system: Optional[str] = None,
        **kwargs,
    ) -> dict:
        raw = await self.complete(prompt, role=role, system=system, **kwargs)
        if not raw:
            return {}
        start = raw.find("{")
        if start == -1:
            return {}
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(raw, start)
            return obj
        except (json.JSONDecodeError, ValueError):
            return {}

    # ── Provider management API (replaces backend.ai.provider_registry) ──

    @staticmethod
    def _provider_meta(name: str, cfg: dict, extra: Optional[dict] = None) -> dict:
        result = {
            "name": name,
            "display_name": cfg.get("display_name", name),
            "tags": cfg.get("tags", []),
            "cost_per_1k_tokens_usd": cfg.get("cost_per_1k_tokens_usd", 0),
            "max_tokens": cfg.get("max_tokens", 0),
            "supports_streaming": cfg.get("supports_streaming", False),
            "supports_tool_use": cfg.get("supports_tool_use", False),
        }
        if extra:
            result.update(extra)
        return result

    def list_available(self) -> list[dict]:
        """Return metadata for all available (enabled + healthy) providers."""
        return [self._provider_meta(name, cfg) for name, cfg in self.providers.items()]

    def get_provider_info(self, name: str) -> Optional[dict]:
        """Get metadata + status for a specific provider."""
        cfg = self.providers.get(name)
        if cfg is None:
            return None
        return self._provider_meta(name, cfg, extra={"enabled": True, "healthy": True})

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a provider by adding/removing from self.providers."""
        if enabled:
            self.providers = _discover_providers()
            if self.default_provider not in self.providers and self.providers:
                self.default_provider = next(iter(self.providers))
        else:
            if name in self.providers:
                del self.providers[name]
                if self.default_provider == name and self.providers:
                    self.default_provider = next(iter(self.providers))
        logger.info(f"AI provider '{name}' {'enabled' if enabled else 'disabled'}")

    def get_best(self, preferred_tags: Optional[list[str]] = None) -> Optional[str]:
        """Return best available provider name matching preferred tags."""
        if not self.providers:
            return None
        if not preferred_tags:
            return self.default_provider
        scored = []
        for name, cfg in self.providers.items():
            tags = set(cfg.get("tags", []))
            score = len(tags & set(preferred_tags))
            scored.append((score, name))
        scored.sort(reverse=True)
        return scored[0][1] if scored else self.default_provider

    async def simple_complete(
        self, prompt: str, system: Optional[str] = None, max_tokens: int = 1000,
        temperature: float = 0.7, **kwargs
    ) -> str:
        """Simple completion using default provider. For code_refactorer compatibility."""
        return await self.complete(prompt, role="default", system=system,
                                   max_tokens=max_tokens, temperature=temperature, **kwargs)

# Singleton
llm_router = LLMRouter()
