"""
MiroFish Mock Server - Simulates MiroFish API for local development

Endpoints:
  GET /health - Health check
  GET / - Root endpoint
  GET /api/simulation/signals?market=polymarket - Return simulated trading signals
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Dict, Any

from backend.config import settings

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mirofish-mock")

app = FastAPI(
    title="MiroFish Mock API",
    description="Simulated MiroFish dual-debate system for local development",
    version="1.0.0"
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simulated signal templates — will be replaced with live Polymarket data on startup
SIGNAL_TEMPLATES: list = []

_fetched_from_polymarket = False


async def _fetch_live_market_templates():
    """Fetch real Polymarket markets to use as signal templates, with retry."""
    global _fetched_from_polymarket, SIGNAL_TEMPLATES
    if _fetched_from_polymarket and SIGNAL_TEMPLATES:
        return

    for attempt in range(3):
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{settings.GAMMA_API_URL}/markets",
                    params={"limit": 20, "active": "true", "closed": "false", "order": "volume", "ascending": "false"},
                )
                resp.raise_for_status()
                markets = resp.json()
                if not markets:
                    raise ValueError("Empty response from Gamma API")
                live_templates = []
                for m in markets[:6]:
                    _outcomes_str = m.get("outcomes", "[]")
                    prices_str = m.get("outcomePrices", "[]")
                    try:
                        prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                        yes_price = float(prices[0]) if prices else 0.5
                    except (json.JSONDecodeError, IndexError, KeyError, ValueError, TypeError):
                        yes_price = 0.5
                    live_templates.append({
                        "market_id": str(m.get("id", f"poly_{len(live_templates)}")),
                        "market_question": str(m.get("question", "Unknown market")),
                        "market_type": str(m.get("category", "crypto")),
                        "prediction": yes_price,
                        "confidence": round(random.uniform(0.55, 0.85), 2),
                        "edge": round(abs(yes_price - 0.5) * random.uniform(0.1, 0.3), 3),
                        "fair_value": round(yes_price + random.uniform(-0.05, 0.05), 3),
                        "current_price": yes_price,
                        "reasoning": f"Live Polymarket: {str(m.get('question', ''))[:80]}...",
                        "sources": ["Polymarket Gamma API", "live order book"],
                    })
                if live_templates:
                    SIGNAL_TEMPLATES = live_templates
                    _fetched_from_polymarket = True
                    logger.info(
                        "MiroFish mock: loaded %d live Polymarket markets (attempt %d)",
                        len(live_templates), attempt + 1,
                    )
                    return
        except Exception as e:
            logger.warning(
                "MiroFish mock: fetch attempt %d/3 failed: %s", attempt + 1, e
            )
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))

    logger.error("MiroFish mock: all fetch attempts failed — signals will use placeholder data")


def generate_signal() -> Dict[str, Any]:
    """Generate a signal using live Polymarket market data as templates."""
    if not SIGNAL_TEMPLATES:
        logger.warning("No market templates available — returning empty signal")
        return {
            "market_id": "unknown",
            "market_question": "Waiting for live market data...",
            "market_type": "unknown",
            "prediction": 0.5,
            "confidence": 0.5,
            "edge": 0.0,
            "fair_value": 0.5,
            "current_price": 0.5,
            "reasoning": "No live Polymarket data available. Check network connectivity.",
            "sources": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signal_id": f"mock_{random.randint(10000, 99999)}",
        }
    template = random.choice(SIGNAL_TEMPLATES)
    noise = random.uniform(-0.05, 0.05)
    return {
        **template,
        "confidence": max(0.5, min(0.95, template["confidence"] + noise)),
        "edge": max(0.02, template["edge"] + noise),
        "current_price": max(0.1, min(0.9, template["current_price"] + noise * 0.5)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signal_id": f"livepoly_{random.randint(10000, 99999)}",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "mirofish-mock",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "MiroFish Mock API",
        "version": "1.0.0",
        "description": "Simulated MiroFish dual-debate system",
        "endpoints": {
            "health": "/health",
            "signals": "/api/simulation/signals?market=polymarket",
        },
    }


@app.get("/api/simulation/signals")
async def get_signals(market: str = Query(default="polymarket", description="Market type")):
    """
    Get simulated trading signals from MiroFish dual-debate system.

    Args:
        market: Market type (polymarket, kalshi, weather, crypto)

    Returns:
        List of trading signals with confidence, edge, and reasoning
    """
    logger.info(f"Generating signals for market: {market}")

    # Generate 1-3 signals
    num_signals = random.randint(1, 3)
    signals = [generate_signal() for _ in range(num_signals)]

    # Filter by market type if specified
    if market != "all":
        signals = [s for s in signals if s["market_type"] == market or market == "polymarket"]

    if not signals:
        # Return at least one signal
        signals = [generate_signal()]

    response = {
        "signals": signals,
        "count": len(signals),
        "market": market,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "mirofish-mock",
    }

    logger.info(f"Returning {len(signals)} signals")
    return response


@app.get("/api/simulation/debate")
async def run_debate(
    market_id: str = Query(..., description="Market ID"),
    question: str = Query(..., description="Market question"),
):
    """
    Simulate a dual-debate analysis for a specific market.

    Args:
        market_id: The market identifier
        question: The market question

    Returns:
        Debate result with YES/NO arguments and final recommendation
    """
    logger.info(f"Running debate for market: {market_id}")

    # Simulate debate outcome
    yes_confidence = random.uniform(0.55, 0.85)
    no_confidence = random.uniform(0.55, 0.85)

    winner = "YES" if yes_confidence > no_confidence else "NO"
    final_confidence = max(yes_confidence, no_confidence)
    edge = abs(yes_confidence - no_confidence) * 0.5

    return {
        "market_id": market_id,
        "question": question,
        "debate_result": {
            "yes_arguments": [
                "Strong fundamental indicators support this outcome",
                "Market sentiment is trending positive",
                "Historical patterns suggest favorable conditions",
            ],
            "no_arguments": [
                "External risks could impact the outcome",
                "Market may be overpricing the probability",
                "Recent data shows conflicting signals",
            ],
            "yes_confidence": yes_confidence,
            "no_confidence": no_confidence,
            "winner": winner,
            "final_confidence": final_confidence,
            "edge": edge,
            "fair_value": final_confidence if winner == "YES" else (1 - final_confidence),
        },
        "recommendation": {
            "action": "BUY" if final_confidence > 0.65 else "HOLD",
            "position": winner,
            "confidence": final_confidence,
            "suggested_size": 0.1 if final_confidence > 0.75 else 0.05,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def main():
    """Run the mock server."""
    await _fetch_live_market_templates()
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=5001,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logger.info("Starting MiroFish Mock Server on port 5001...")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
