"""Regression tests for scheduled Polymarket auto-redemption."""

from dataclasses import dataclass, field

import pytest


@dataclass
class _BatchResult:
    total_attempted: int = 0
    total_redeemed: int = 0
    total_failed: int = 0
    total_usdc_recovered: float = 0.0
    errors: list[str] = field(default_factory=list)
    results: list[object] = field(default_factory=list)


@pytest.mark.asyncio
async def test_auto_redeem_job_skips_without_wallet_or_key(monkeypatch):
    """The scheduled job must not call redemption code without signing credentials."""

    from backend.core import scheduling_strategies
    from backend.core import scheduler as scheduler_module
    import backend.core.auto_redeem as auto_redeem_module

    events: list[tuple[str, str]] = []
    called = False

    def fake_log_event(event_type: str, message: str, data: dict | None = None):
        events.append((event_type, message))

    def fake_redeem_all_redeemable(*args, **kwargs):
        nonlocal called
        called = True
        return _BatchResult()

    monkeypatch.setattr(scheduling_strategies.settings, "AUTO_REDEEM_ENABLED", True, raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_BUILDER_ADDRESS", None, raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_WALLET_ADDRESS", None, raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_PRIVATE_KEY", None, raising=False)
    monkeypatch.setattr(scheduler_module, "log_event", fake_log_event)
    monkeypatch.setattr(auto_redeem_module, "redeem_all_redeemable", fake_redeem_all_redeemable)

    await scheduling_strategies.auto_redeem_job()

    assert called is False
    assert any(event_type == "warning" and "skipped" in message for event_type, message in events)


@pytest.mark.asyncio
async def test_auto_redeem_job_uses_dry_run_by_default(monkeypatch):
    """The scheduler should default to reporting redeemables unless live redemption is enabled."""

    from backend.core import scheduling_strategies
    from backend.core import scheduler as scheduler_module
    import backend.core.auto_redeem as auto_redeem_module

    captured: dict[str, object] = {}

    def fake_log_event(event_type: str, message: str, data: dict | None = None):
        captured["event_type"] = event_type
        captured["message"] = message
        captured["data"] = data or {}

    def fake_redeem_all_redeemable(**kwargs):
        captured.update(kwargs)
        return _BatchResult(total_attempted=2, total_redeemed=2)

    monkeypatch.setattr(scheduling_strategies.settings, "AUTO_REDEEM_ENABLED", True, raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "AUTO_REDEEM_DRY_RUN", True, raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "AUTO_REDEEM_TIMEOUT_SECONDS", 5, raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_BUILDER_ADDRESS", "0xWallet", raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_WALLET_ADDRESS", None, raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_PRIVATE_KEY", "0xPrivateKey", raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_BUILDER_API_KEY", "builder-key", raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_BUILDER_SECRET", "builder-secret", raising=False)
    monkeypatch.setattr(scheduling_strategies.settings, "POLYMARKET_BUILDER_PASSPHRASE", "builder-passphrase", raising=False)
    monkeypatch.setattr(scheduler_module, "log_event", fake_log_event)
    monkeypatch.setattr(auto_redeem_module, "redeem_all_redeemable", fake_redeem_all_redeemable)

    await scheduling_strategies.auto_redeem_job()

    assert captured["wallet"] == "0xWallet"
    assert captured["private_key"] == "0xPrivateKey"
    assert captured["dry_run"] is True
    assert captured["builder_api_key"] == "builder-key"
    assert captured["event_type"] == "info"
