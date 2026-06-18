"""Hackathon API router — CMC Skills, autonomous agent, and BNB Hack submission endpoints."""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.config import settings
from loguru import logger

# Lazily imported to avoid circular deps at module level

router = APIRouter(prefix="/api/v1/hackathon", tags=["hackathon"])


# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------

class CMCSkillRequest(BaseModel):
    symbols: Optional[List[str]] = None
    lookback_hours: Optional[int] = 24
    min_divergence_pct: Optional[float] = 2.0

class CMCSkillResponse(BaseModel):
    success: bool
    skill_name: str
    result: Dict[str, Any]
    execution_time_ms: float
    timestamp: str

class AgentSignalRequest(BaseModel):
    action: str  # "buy" | "sell" | "hold"
    token: str
    amount: str
    confidence: float
    reason: str = ""

class AgentStatusResponse(BaseModel):
    agent_id: Optional[str]
    registered: bool
    paper_balance: float
    open_positions: int
    cmc_connected: bool
    twak_connected: bool
    bnb_agent_ready: bool

class MarketSnapshotResponse(BaseModel):
    timestamp: str
    top_assets: Dict[str, Any]
    global_metrics: Dict[str, Any]
    regime: Dict[str, Any]
    risk: Dict[str, Any]

# ------------------------------------------------------------------
# Lazy loaders
# ------------------------------------------------------------------

try:
    from backend.data.crypto_feeds.registry import get_registry as get_feed_registry
    _FEED_AVAILABLE = True
except ImportError:
    _FEED_AVAILABLE = False

try:
    from backend.modules.cmc_skills import (
        register_all_cmc_skills,
        get_cmc_skill_registry,
        CMCSkillResult,
    )
    _SKILLS_AVAILABLE = True
except ImportError:
    _SKILLS_AVAILABLE = False

try:
    from backend.clients.twak_client import TWAKClient, TWAKConfig
    _TWAK_AVAILABLE = True
except ImportError:
    _TWAK_AVAILABLE = False

try:
    from backend.clients.bnb_agent_client import BNBAgentClient, BNBAgentConfig
    _BNB_AGENT_AVAILABLE = True
except ImportError:
    _BNB_AGENT_AVAILABLE = False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_cmc_feed():
    if not _FEED_AVAILABLE:
        return None
    registry = get_feed_registry()
    return registry._plugins.get("coinmarketcap")

def _get_twak():
    if not _TWAK_AVAILABLE:
        return None
    return TWAKClient(TWAKConfig(autonomous_mode=True))

def _get_bnb_agent():
    if not _BNB_AGENT_AVAILABLE:
        return None
    return BNBAgentClient()


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/status", summary="Hackathon subsystem health check")
async def hackathon_health() -> Dict[str, Any]:
    """Health check for all hackathon subsystems."""
    cmc_feed = _get_cmc_feed()
    cmc_ok = False
    if cmc_feed:
        try:
            cmc_ok = await cmc_feed.health_check()
        except Exception:
            cmc_ok = False

    twak_ok = False
    twak = _get_twak()
    if twak:
        try:
            twak_ok = await twak.health_check()
        except Exception:
            twak_ok = False

    bnb_ok = _BNB_AGENT_AVAILABLE
    skills_ok = _SKILLS_AVAILABLE

    return {
        "status": "healthy" if (cmc_ok or skills_ok) else "degraded",
        "coinmarketcap_data": {"available": cmc_ok, "feed_loaded": cmc_feed is not None},
        "twak_execution": {"available": twak_ok, "cli_found": twak is not None},
        "bnb_agent_sdk": {"available": bnb_ok, "package_installed": _BNB_AGENT_AVAILABLE},
        "cmc_skills": {"registered": skills_ok},
        "track1_ready": twak_ok and cmc_ok,
        "track2_ready": skills_ok and cmc_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/market", summary="CMC market snapshot + analysis")
async def market_snapshot() -> MarketSnapshotResponse:
    """Full market snapshot: CMC data, regime analysis, risk assessment."""
    cmc = _get_cmc_feed()
    if not cmc:
        raise HTTPException(503, "CMC feed not available. Install and configure CMC_PRO_API_KEY.")

    snapshot = await cmc.mcp_get_market_snapshot()
    global_metrics = await cmc.get_global_metrics()

    if _SKILLS_AVAILABLE:
        registry = get_cmc_skill_registry()
        regime_result = await registry.execute("cmc_market_regime")
        risk_result = await registry.execute("cmc_risk_assessment")
    else:
        regime_result = CMCSkillResult(skill_name="cmc_market_regime", success=False)
        risk_result = CMCSkillResult(skill_name="cmc_risk_assessment", success=False)

    global_data = global_metrics.get("data", {})

    return MarketSnapshotResponse(
        timestamp=snapshot.get("timestamp", datetime.now(timezone.utc).isoformat()),
        top_assets=snapshot.get("top_assets", {}),
        global_metrics={
            "total_market_cap": global_data.get("quote", {}).get("USD", {}).get("total_market_cap"),
            "btc_dominance": global_data.get("btc_dominance"),
            "eth_dominance": global_data.get("eth_dominance"),
            "active_cryptocurrencies": global_data.get("active_cryptocurrencies"),
        },
        regime=regime_result.analysis if regime_result.success else {"error": "regime analysis unavailable"},
        risk=risk_result.analysis if risk_result.success else {"error": "risk assessment unavailable"},
    )


# ------------------------------------------------------------------
# Track 2: CMC Skills API
# ------------------------------------------------------------------

@router.get("/skills", summary="List all registered CMC Skills")
async def list_skills() -> Dict[str, Any]:
    """List available Track 2 CMC Skills for the Skills Marketplace."""
    if not _SKILLS_AVAILABLE:
        raise HTTPException(503, "CMC Skills module not loaded.")

    registry = get_cmc_skill_registry()
    skills = registry.list_skills()

    return {
        "skills": skills,
        "count": len(skills),
        "marketplace_url": "https://coinmarketcap.com/api/skills-marketplace/",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/skills/{name}/run", summary="Execute a CMC Skill")
async def execute_skill(name: str, req: CMCSkillRequest) -> CMCSkillResponse:
    """Execute a registered CMC Skill with the provided parameters."""
    if not _SKILLS_AVAILABLE:
        raise HTTPException(503, "CMC Skills module not loaded.")

    registry = get_cmc_skill_registry()
    manifest = registry.get_skill(name)
    if manifest is None:
        raise HTTPException(404, f"Skill '{name}' not found")

    kwargs = {}
    if req.symbols:
        kwargs["symbols"] = req.symbols
    if req.lookback_hours:
        kwargs["lookback_hours"] = req.lookback_hours
    if req.min_divergence_pct:
        kwargs["min_divergence_pct"] = req.min_divergence_pct

    result = await registry.execute(name, feed=_get_cmc_feed(), **kwargs)

    return CMCSkillResponse(
        success=result.success,
        skill_name=name,
        result=result.analysis if result.analysis else {"signals": [s.to_dict() if hasattr(s, 'to_dict') else s for s in result.signals]},
        execution_time_ms=manifest.execution_time_ms,
        timestamp=result.timestamp,
    )


# ------------------------------------------------------------------
# Track 1: Autonomous Trading Agent
# ------------------------------------------------------------------

@router.post("/trade", summary="Execute a trading signal via TWAK")
async def execute_agent_signal(signal: AgentSignalRequest) -> Dict[str, Any]:
    """Execute a trading signal through the autonomous agent pipeline.

    CMC signal → AGI analysis → TWAK execution on BSC.
    """
    twak = _get_twak()
    if not twak:
        raise HTTPException(503, "TWAK client not available. Install: curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash")

    rules = {
        "min_confidence": 0.6,
        "allowed_tokens": ["USDC", "USDT", "WBNB", "ETH", "BTCB", "SOL", "CAKE"],
        "max_position_pct": 0.1,
    }

    result = await twak.autonomous_trade(
        signal=signal.model_dump(),
        rules=rules,
    )

    return {
        "success": result.get("success", False),
        "action": signal.action,
        "token": signal.token,
        "amount": signal.amount,
        "confidence": signal.confidence,
        "execution_result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/agent", summary="Autonomous trading agent status")
async def agent_status() -> AgentStatusResponse:
    """Get status of the autonomous trading agent for Track 1."""
    cmc = _get_cmc_feed()
    twak = _get_twak()
    bnb = _get_bnb_agent()

    cmc_ok = False
    if cmc:
        try:
            cmc_ok = await cmc.health_check()
        except Exception:
            cmc_ok = False

    twak_ok = False
    twak_portfolio = {}
    if twak:
        try:
            twak_ok = await twak.health_check()
            if twak_ok:
                twak_portfolio = await twak.wallet_portfolio()
        except Exception:
            twak_ok = False

    bnb_ready = False
    if bnb:
        try:
            bnb_ready = await bnb.health_check()
        except Exception:
            bnb_ready = False

    portfolio = twak_portfolio.get("data", twak_portfolio) if twak_portfolio else {}

    return AgentStatusResponse(
        agent_id=portfolio.get("agent_id"),
        registered=bnb_ready,
        paper_balance=10000.0,
        open_positions=len(portfolio.get("positions", [])),
        cmc_connected=cmc_ok,
        twak_connected=twak_ok,
        bnb_agent_ready=bnb_ready,
    )


# ------------------------------------------------------------------
# BNB Agent identity registration
# ------------------------------------------------------------------

class AgentRegistrationRequest(BaseModel):
    name: str = "PolyEdge Autonomous Trader"
    description: str = ""
    register_on_chain: bool = False

@router.post("/agent/onchain", summary="Register agent on BSC (ERC-8004)")
async def register_agent(req: AgentRegistrationRequest) -> Dict[str, Any]:
    """Register trading agent identity on BSC via BNB Agent SDK (ERC-8004)."""
    if not _BNB_AGENT_AVAILABLE:
        raise HTTPException(503, "bnbagent SDK not installed. Install: pip install bnbagent")

    bnb = _get_bnb_agent()
    try:
        await bnb.initialize()
        agent_info = await bnb.get_agent_info()

        if req.register_on_chain:
            result = await bnb.register_trading_agent(strategy_name=req.name)
            return {
                "status": "registered_on_chain",
                "agent_id": result.get("agent_id"),
                "transaction_hash": result.get("transaction_hash"),
                "network": agent_info.get("network"),
                "address": agent_info.get("address"),
            }

        return {
            "status": "ready_to_register",
            "info": agent_info,
            "message": "Call with register_on_chain=true to submit ERC-8004 registration",
        }
    except Exception as e:
        logger.exception(f"Agent registration failed: {e}")
        raise HTTPException(500, f"Agent registration failed: {e}")


# ------------------------------------------------------------------
# BNB HACK Bot endpoints
# ------------------------------------------------------------------

@router.get("/bnb-hack/status", summary="BNB HACK bot status and PnL")
async def bnb_hack_status() -> Dict[str, Any]:
    """Get current BNB HACK bot status: position, PnL, risk metrics."""
    try:
        from backend.bot.bnb_hack import BnbHackBot
        bot = BnbHackBot.from_config(paper=False)

        price = await bot.feed.get_price("BNBUSDT")
        bal = await bot.exchange.balance()

        has_pos = bot.has_position()
        pnl_trade = 0.0
        if has_pos:
            pos = list(bot.state.positions.values())[0]
            pnl_trade = ((price - pos.entry_price) / pos.entry_price) * 100

        await bot.close()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "chain": "bsc",
            "position": {
                "open": has_pos,
                "token": "BNB" if has_pos else None,
                "entry_price": list(bot.state.positions.values())[0].entry_price if has_pos else None,
                "current_price": price,
                "unrealized_pnl_pct": round(pnl_trade, 2) if has_pos else None,
            },
            "pnl": {
                "total_usd": round(bot.state.total_pnl_usd, 2),
                "daily_usd": round(bot.state.daily_pnl_usd, 2),
                "trades_today": bot.state.trades_today,
                "consecutive_losses": bot.state.consecutive_losses,
            },
            "risk": {
                "in_cooldown": bot.state.in_cooldown,
                "cooldown_until": bot.state.cooldown_until.isoformat() if bot.state.cooldown_until else None,
            },
            "balance": bal,
        }
    except Exception as e:
        logger.error("BNB HACK status endpoint error: {}", e)
        raise HTTPException(500, f"Failed to get bot status: {e}")


@router.get("/bnb-hack/signal", summary="Current BNB HACK market signal")
async def bnb_hack_signal() -> Dict[str, Any]:
    """Get current SMA crossover signal for BNB/USDT 1h."""
    try:
        from backend.bot.bnb_hack import BnbHackBot
        bot = BnbHackBot.from_config(paper=False)

        sig = await bot.signals.evaluate()
        await bot.close()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": sig["action"],
            "confidence": sig["confidence"],
            "reason": sig["reason"],
            "price": sig["price"],
            "indicators": sig["indicators"],
        }
    except Exception as e:
        logger.error("BNB HACK signal endpoint error: {}", e)
        raise HTTPException(500, f"Failed to get signal: {e}")


@router.get("/bnb-hack/trades", summary="Recent BNB HACK trades")
async def bnb_hack_trades(limit: int = 20) -> Dict[str, Any]:
    """Get recent trades from trade log."""
    import csv
    from pathlib import Path

    try:
        log_path = Path("logs/bnb_hack_trades.csv")
        trades = []

        if log_path.exists():
            with open(log_path, "r") as f:
                reader = csv.DictReader(f)
                for row in list(reader)[-limit:]:
                    trades.append({
                        "timestamp": row["timestamp"],
                        "action": row["action"],
                        "token": row["token"],
                        "price": float(row["price"]),
                        "amount_usdc": float(row["amount_usdc"]),
                        "amount_token": float(row["amount_token"]),
                        "pnl_usdc": float(row["pnl_usdc"]),
                        "reason": row["reason"],
                    })

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_count": len(trades),
            "trades": trades,
        }
    except Exception as e:
        logger.error("BNB HACK trades endpoint error: {}", e)
        raise HTTPException(500, f"Failed to get trades: {e}")


# ------------------------------------------------------------------
# BNB Hack submission helper
# ------------------------------------------------------------------

@router.get("/manifest", summary="Hackathon submission summary")
async def submission_summary() -> Dict[str, Any]:
    """Generate a structured summary for BNB HACK submission.

    Includes: agent identity, CMC skills, architecture overview, and links.
    """
    registry = get_cmc_skill_registry() if _SKILLS_AVAILABLE else None
    skills = registry.list_skills() if registry else []
    cmc = _get_cmc_feed()
    cmc_ok = await cmc.health_check() if cmc else False

    return {
        "project_name": "PolyEdge — Autonomous Trading Agent & Strategy Skill Suite",
        "hackathon": "BNB HACK: AI Trading Agent Edition",
        "tracks": {
            "track_1": {
                "name": "Autonomous Trading Agents",
                "status": "ready" if _TWAK_AVAILABLE else "requires_twak_install",
                "components": [
                    "CoinMarketCap Data API feed (live prices, OHLCV, trends, sentiment)",
                    "Trust Wallet Agent Kit execution layer (BSC swaps, portfolio, alerts)",
                    "BNB Agent SDK (ERC-8004 identity registration on BSC Testnet)",
                    "AGI debate engine for signal validation before execution",
                    "Kelly sizing + drawdown protection risk controls",
                ],
                "live_trading_window": "June 22-28, 2026",
            },
            "track_2": {
                "name": "Strategy Skills",
                "status": "ready",
                "skills": skills,
                "backtesting": True,
                "components": [
                    "CMC Momentum Scanner — multi-asset momentum signals with RSI + SMA",
                    "CMC Market Regime Classifier — regime-aware strategy allocation",
                    "CMC Cross-Asset Divergence Scanner — mean-reversion opportunities",
                    "CMC Risk Assessment Engine — volatility scoring + position sizing",
                    "CMC Market Sentiment Analyzer — sentiment scoring from trends + RSI",
                ],
            },
        },
        "sponsor_stack": {
            "coinmarketcap": {
                "version": "Data API v2 + MCP + Skills",
                "integrated": cmc_ok,
                "endpoints": [
                    "/v2/cryptocurrency/quotes/latest",
                    "/v2/cryptocurrency/ohlcv/latest",
                    "/v1/global-metrics/quotes/latest",
                    "/v1/cryptocurrency/trending/latest",
                ],
            },
            "trust_wallet": {
                "version": "TWAK CLI v0.12+",
                "mode": "Autonomous Agent Wallet (Mode A)",
                "capabilities": ["swap", "limit_orders", "dca", "price_alerts", "x402"],
            },
            "bnb_chain": {
                "version": "BNB Agent SDK (bnbagent)",
                "capabilities": ["ERC-8004 Agent Identity", "ERC-8183 Agentic Commerce"],
                "network": "BSC Testnet / Mainnet",
            },
        },
        "deployment": {
            "backend": "uvicorn backend.api.main:app --port 8100",
            "docs": "/api/v1/hackathon/status",
            "twak_install": "curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash",
            "bnb_sdk": "pip install bnbagent",
        },
        "submission_lock": "June 21, 2026 12:00pm UTC",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
