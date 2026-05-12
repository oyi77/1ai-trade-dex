"""Unified LLM provider routing layer."""

import json
from typing import Optional

from loguru import logger
ROLE_SETTING_MAP = {
    "default": "LLM_DEFAULT_PROVIDER",
    "debate_agent": "LLM_DEBATE_PROVIDER",
    "judge": "LLM_JUDGE_PROVIDER",
    "claude_escalation": "claude",
}


class LLMRouter:
    def __init__(self):
        from backend.config import settings

        self.providers: dict[str, dict] = {}
        self.default_provider: str = getattr(settings, "LLM_DEFAULT_PROVIDER", "groq")

        if settings.GROQ_API_KEY:
            self.providers["groq"] = {
                "api_key": settings.GROQ_API_KEY,
                "model": settings.GROQ_MODEL,
                "base_url": None,
                "max_tokens": 250,
                "temperature": 0.2,
            }

        anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", None)
        if anthropic_key:
            self.providers["claude"] = {
                "api_key": anthropic_key,
                "model": getattr(
                    settings, "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
                ),
                "base_url": None,
                "max_tokens": 300,
                "temperature": 0.2,
            }

    def _resolve_provider(self, role: str) -> Optional[str]:
        from backend.config import settings

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
        from groq import AsyncGroq

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
        from anthropic import AsyncAnthropic

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

    async def _dispatch(
        self, provider_name: str, config: dict, messages: list[dict], **kwargs
    ) -> tuple[str, int]:
        if provider_name == "groq":
            return await self._call_groq(config, messages, **kwargs)
        if provider_name == "claude":
            return await self._call_claude(config, messages, **kwargs)
        raise ValueError(f"Unknown provider: {provider_name}")

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

        last_error: Optional[Exception] = None
        for provider_name in self._fallback_order(primary):
            config = self.providers[provider_name]
            try:
                text, _tokens = await self._dispatch(
                    provider_name, config, messages, **kwargs
                )
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
