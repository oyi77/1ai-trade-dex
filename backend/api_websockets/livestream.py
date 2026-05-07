import logging
import asyncio
from typing import Dict, Any, List
from datetime import datetime, timezone

from backend.core.task_manager import TaskManager

logger = logging.getLogger(__name__)

_task_manager = None

def set_task_manager(tm):
    global _task_manager
    _task_manager = tm


def get_task_manager():
    return _task_manager

_pipeline_cards: List[Dict[str, Any]] = []
_max_cards = 50

_arena_state = {
    "bull_text": "",
    "bear_text": "",
    "verdict": None,
    "is_debating": False,
    "current_signal": None,
}

_pulse_state: Dict[str, Dict[str, Any]] = {}


async def broadcast_signal_detected(signal: Any):

    if isinstance(signal, TradingSignal):
        data = {
            "id": f"sig_{datetime.now(timezone.utc).timestamp():.0f}",
            "signal": f"{signal.market_slug or signal.event_slug}",
            "confidence": signal.confidence,
            "edge": getattr(signal, "edge", 0.0),
            "source": getattr(signal, "source", "unknown"),
            "strategy": getattr(signal, "strategy_name", "unknown"),
        }
    else:
        data = signal

    card = {
        "id": data.get("id", f"sig_{datetime.now(timezone.utc).timestamp():.0f}"),
        "signal": data.get("signal", "Unknown signal"),
        "stage": "detected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": data.get("confidence", 0.0),
        "edge": data.get("edge", 0.0),
        "source": data.get("source", "unknown"),
        "strategy": data.get("strategy", "unknown"),
    }

    _pipeline_cards.append(card)
    if len(_pipeline_cards) > _max_cards:
        _pipeline_cards.pop(0)

    message = {
        "type": "pipeline_update",
        "action": "card_added",
        "stage": "detected",
        "card": card,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("livestream", message),
            name="ls_signal_detected"
        )
    else:
        asyncio.create_task(topic_manager.broadcast("livestream", message))
    logger.debug(f"Broadcast signal_detected: {card['signal']}")


async def broadcast_stage_transition(card_id: str, new_stage: str, **kwargs):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "pipeline_update",
        "action": "stage_transition",
        "card_id": card_id,
        "stage": new_stage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("livestream", message),
            name=f"ls_stage_{new_stage}"
        )
    else:
        asyncio.create_task(topic_manager.broadcast("livestream", message))
    logger.debug(f"Broadcast stage_transition: {card_id} → {new_stage}")


async def broadcast_debate_update(bull_text: str = "", bear_text: str = "", verdict: str = None, is_debating: bool = True):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "arena_update",
        "bull_text": bull_text,
        "bear_text": bear_text,
        "verdict": verdict,
        "is_debating": is_debating,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("livestream", message),
            name="ls_debate_update"
        )
    else:
        asyncio.create_task(topic_manager.broadcast("livestream", message))
    logger.debug(f"Broadcast arena_update: verdict={verdict}, debating={is_debating}")


async def broadcast_strategy_pulse(strategy_name: str, status: str, **kwargs):
    from backend.api.ws_manager_v2 import topic_manager

    global _pulse_state
    _pulse_state[strategy_name] = {
        "name": strategy_name,
        "status": status,
        "last_pulse": datetime.now(timezone.utc).timestamp(),
        **kwargs,
    }

    message = {
        "type": "pulse_update",
        "strategy": strategy_name,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("livestream", message),
            name=f"ls_pulse_{strategy_name}"
        )
    else:
        asyncio.create_task(topic_manager.broadcast("livestream", message))
    logger.debug(f"Broadcast pulse_update: {strategy_name} → {status}")


async def broadcast_thought_log(text: str):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "thought_log",
        "id": f"th_{datetime.now(timezone.utc).timestamp():.3f}",
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("livestream", message),
            name="ls_thought_log"
        )
    else:
        asyncio.create_task(topic_manager.broadcast("livestream", message))
    logger.debug(f"Broadcast thought_log: {text[:30]}...")

async def broadcast_trade_event(trade_data: Dict[str, Any]):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "trade_event",
        "action": "trade_" + ("executed" if trade_data.get("settled") else "blocked"),
        "trade": trade_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("livestream", message),
            name="ls_trade_event"
        )
    else:
        asyncio.create_task(topic_manager.broadcast("livestream", message))
    logger.debug(f"Broadcast trade_event: {trade_data.get('id')}")


async def broadcast_livestream_snapshot():
    from backend.api.ws_manager_v2 import topic_manager

    snapshot = {
        "type": "livestream_snapshot",
        "pipeline_cards": list(_pipeline_cards),
        "arena": dict(_arena_state),
        "pulse_strategies": list(_pulse_state.values()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("livestream", snapshot),
            name="ls_snapshot"
        )
    else:
        asyncio.create_task(topic_manager.broadcast("livestream", snapshot))
    logger.debug("Broadcast livestream_snapshot")


# ---------------------------------------------------------------------------
# Livestream broadcaster task (runs in lifespan)
# ---------------------------------------------------------------------------

async def livestream_broadcaster():
    from backend.api.ws_manager_v2 import topic_manager
    from backend.models.database import SessionLocal, BotState, Trade, StrategyConfig, TradeAttempt, for_update
    import json
    import time

    logger.info("Livestream broadcaster task started")

    last_trade_check = 0
    last_strategy_check = 0
    last_arena_check = 0

    while True:
        try:
            sub_count = topic_manager.get_topic_subscriber_count("livestream")
            if sub_count == 0:
                await asyncio.sleep(2)
                continue

            now = time.time()

            if now - last_strategy_check > 3:
                last_strategy_check = now
                try:
                    db = SessionLocal()
                    try:
                        strategies = db.query(StrategyConfig).all()
                        for cfg in strategies:
                            status = "thinking" if cfg.enabled else "idle"
                            await broadcast_strategy_pulse(cfg.strategy_name, status)
                    finally:
                        db.close()
                except Exception as e:
                    logger.debug(f"Livestream strategy pulse error: {e}")

            if now - last_trade_check > 2:
                last_trade_check = now
                try:
                    db = SessionLocal()
                    try:
                        recent_trade = (
                            db.query(Trade)
                            .order_by(Trade.timestamp.desc())
                            .first()
                        )
                        if recent_trade and recent_trade.timestamp:
                            trade_data = {
                                "id": recent_trade.id,
                                "market_ticker": recent_trade.market_ticker,
                                "direction": recent_trade.direction,
                                "entry_price": float(recent_trade.entry_price or 0),
                                "size": float(recent_trade.size or 0),
                                "pnl": float(recent_trade.pnl or 0),
                                "settled": recent_trade.settled,
                                "timestamp": recent_trade.timestamp.isoformat() if recent_trade.timestamp else "",
                            }
                            await broadcast_trade_event(trade_data)
                    finally:
                        db.close()
                except Exception as e:
                    logger.debug(f"Livestream trade check error: {e}")

            if now - last_arena_check > 5:
                last_arena_check = now
                try:
                    db = SessionLocal()
                    try:
                        recent_attempt = (
                            db.query(TradeAttempt)
                            .order_by(TradeAttempt.created_at.desc())
                            .first()
                        )
                        if recent_attempt:
                            reason = recent_attempt.reason or ""
                            sig_data = json.loads(recent_attempt.signal_data) if recent_attempt.signal_data else {}
                            if sig_data and "reasoning" in sig_data:
                                reason = sig_data["reasoning"]
                                
                            dir_bias = recent_attempt.direction or "unknown"
                            market = recent_attempt.market_ticker or "Unknown"
                            conf = getattr(recent_attempt, "confidence", 0) or 0
                            edge = getattr(recent_attempt, "edge", 0) or 0
                            
                            bull_text = f"Analyzing market {market}...\nDirectional bias: {dir_bias.upper()}\n"
                            bear_text = f"Risk checks...\nConfidence: {conf*100:.1f}%\nEdge: {edge*100:.1f}%\n"
                            
                            for part in reason.split():
                                if "=" in part:
                                    k, v = part.split("=", 1)
                                    if k in ["btc", "eth"]:
                                        bull_text += f"Live {k.upper()} price: {v}\n"
                                    elif k == "t":
                                        bear_text += f"Time window: {v}\n"
                                    else:
                                        bull_text += f"Metric {k}: {v}\n"
                            
                            bull_text += f"\nConclusion: Market supports signal."
                            bear_text += f"\nRisk check: {'Passed' if recent_attempt.status == 'executed' else 'Blocked'}"
                            
                            await broadcast_debate_update(
                                bull_text=bull_text,
                                bear_text=bear_text,
                                verdict=dir_bias.lower() if dir_bias.lower() in ["bull", "bear", "up", "down"] else None,
                                is_debating=False
                            )
                            
                            await broadcast_thought_log(f"Analyzed {market} (bias: {dir_bias.upper()}). Confidence: {conf*100:.1f}%, Edge: {edge*100:.1f}%. Result: {recent_attempt.status.upper()}")
                            if reason:
                                await broadcast_thought_log(f"Reasoning keys: {reason}")

                    finally:
                        db.close()
                except Exception as e:
                    logger.debug(f"Livestream arena check error: {e}")

            if now - last_trade_check > 10:
                try:
                    db = SessionLocal()
                    try:
                        bot_state = for_update(db, db.query(BotState)).first()
                        if bot_state:
                            await topic_manager.broadcast("livestream", {
                                "type": "bot_state",
                                "bankroll": float(bot_state.bankroll or 0),
                                "total_pnl": float(bot_state.total_pnl or 0),
                                "total_trades": bot_state.total_trades or 0,
                                "is_running": bot_state.is_running,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                    finally:
                        db.close()
                except Exception as e:
                    logger.debug(f"Livestream bot state error: {e}")

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Livestream broadcaster cancelled")
            break
        except Exception as e:
            logger.warning(f"Livestream broadcaster error: {e}", exc_info=True)
            await asyncio.sleep(5)


def get_pipeline_cards():
    return list(_pipeline_cards)


def get_arena_state():
    return dict(_arena_state)


def get_pulse_state():
    return dict(_pulse_state)
