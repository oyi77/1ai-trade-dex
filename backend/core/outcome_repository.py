from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from backend.models.outcome_tables import StrategyOutcome, ParamChange


def compute_reward(trade, recent_sharpe: float = 1.0, recent_drawdown_pct: float = 0.0, mode_weight: float = 1.0) -> float:
    """Sharpe-adjusted PnL reward. paper=1x, testnet=10x, live=100x"""
    pnl = getattr(trade, 'pnl', 0.0) or 0.0
    if pnl > 0:
        reward = pnl / max(1.0, recent_sharpe)
    else:
        reward = pnl * max(1.0, abs(recent_drawdown_pct))
    return reward * mode_weight


def record_outcome(trade, db) -> Optional[StrategyOutcome]:
    """Insert a StrategyOutcome from a settled Trade. Returns None on error or duplicate."""
    import logging
    _logger = logging.getLogger(__name__)
    try:
        trade_id = getattr(trade, 'id', None)
        if trade_id is not None:
            existing = db.query(StrategyOutcome).filter(StrategyOutcome.trade_id == trade_id).first()
            if existing:
                return existing

        mode_weights = {'paper': 1.0, 'testnet': 10.0, 'live': 100.0}
        mode = getattr(trade, 'trading_mode', 'paper') or 'paper'
        weight = mode_weights.get(mode, 1.0)
        reward = compute_reward(trade, mode_weight=weight)
        outcome = StrategyOutcome(
            strategy=getattr(trade, 'strategy', 'unknown') or 'unknown',
            market_ticker=getattr(trade, 'market_ticker', '') or '',
            market_type=getattr(trade, 'market_type', 'unknown') or 'unknown',
            trading_mode=mode,
            direction=getattr(trade, 'direction', 'unknown') or 'unknown',
            model_probability=getattr(trade, 'model_probability', None),
            market_price=getattr(trade, 'market_price_at_entry', None),
            edge_at_entry=getattr(trade, 'edge_at_entry', None),
            confidence=getattr(trade, 'confidence', None),
            result=getattr(trade, 'result', None),
            pnl=getattr(trade, 'pnl', None),
            reward=reward,
            settled_at=getattr(trade, 'settlement_time', None) or datetime.now(timezone.utc),
            trade_id=trade.id,
        )
        db.add(outcome)
        db.commit()
        return outcome
    except Exception as e:
        _logger.warning(f"[outcome_repository] record_outcome failed for trade {getattr(trade, 'id', '?')}: {e}")
        db.rollback()
        return None


def get_strategy_stats(strategy: str, market_type: Optional[str], db) -> Optional[Dict[str, Any]]:
    """Return win rate, Sharpe, drawdown for a strategy. Returns None if no data."""
    try:
        q = db.query(StrategyOutcome).filter(StrategyOutcome.strategy == strategy)
        if market_type:
            q = q.filter(StrategyOutcome.market_type == market_type)
        outcomes = q.all()
        if not outcomes:
            return None
        wins = sum(1 for o in outcomes if o.result == 'win')
        losses = sum(1 for o in outcomes if o.result == 'loss')
        total = len(outcomes)
        pnls = [o.pnl for o in outcomes if o.pnl is not None]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        std_pnl = (sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5 if len(pnls) > 1 else 1.0
        sharpe = avg_pnl / max(std_pnl, 1e-9)
        return {
            'strategy': strategy,
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': wins / total if total > 0 else 0.0,
            'sharpe': sharpe,
            'avg_pnl': avg_pnl,
        }
    except Exception:
        return None


def get_recent_outcomes(strategy: str, limit: int, db) -> List[StrategyOutcome]:
    """Return last N outcomes for a strategy."""
    try:
        return (db.query(StrategyOutcome)
                .filter(StrategyOutcome.strategy == strategy)
                .order_by(StrategyOutcome.settled_at.desc())
                .limit(limit)
                .all())
    except Exception:
        return []


def record_param_change(strategy: str, param: str, old_val: float, new_val: float, db) -> Optional[ParamChange]:
    """Insert a ParamChange record."""
    try:
        change_pct = ((new_val - old_val) / max(abs(old_val), 1e-9)) * 100 if old_val != 0 else 0.0
        change = ParamChange(
            strategy=strategy,
            param_name=param,
            old_value=old_val,
            new_value=new_val,
            change_pct=change_pct,
            applied_at=datetime.now(timezone.utc),
            auto_applied=False,
        )
        db.add(change)
        db.commit()
        return change
    except Exception:
        db.rollback()
        return None


def mark_param_reverted(change_id: int, post_sharpe: float, db) -> None:
    """Mark a param change as reverted."""
    try:
        change = db.query(ParamChange).filter(ParamChange.id == change_id).first()
        if change:
            change.reverted_at = datetime.now(timezone.utc)
            change.post_change_sharpe = post_sharpe
            db.commit()
    except Exception:
        db.rollback()


def backfill_missing_outcomes(db) -> int:
    """Backfill strategy_outcomes for settled trades missing outcomes. Returns count."""
    import logging
    _logger = logging.getLogger(__name__)
    try:
        from backend.models.database import Trade
        existing_ids = set(r[0] for r in db.query(StrategyOutcome.trade_id).all())
        settled = db.query(Trade).filter(
            Trade.settled == True,
            Trade.result.in_(["win", "loss"]),
        ).all()
        missing = [t for t in settled if t.id not in existing_ids]
        if not missing:
            return 0
        count = 0
        for t in missing:
            outcome = record_outcome(t, db)
            if outcome:
                count += 1
        _logger.info(f"[outcome_repository] Backfilled {count} missing outcomes from {len(missing)} settled trades")
        return count
    except Exception as e:
        _logger.warning(f"[outcome_repository] backfill failed: {e}")
        return 0
