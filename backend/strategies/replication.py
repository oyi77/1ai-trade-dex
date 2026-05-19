"""Strategy Replication — Extract decision rules from profitable wallets.

Takes a source wallet's trading history, fingerprints its strategy,
decomposes into executable rules, and validates via paper simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from backend.data.wallet_history import get_all_closed_positions
from backend.strategies.fingerprint import StrategyFingerprint, strategy_fingerprint


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Rule:
    """A single replicated trading rule derived from pattern analysis."""

    condition: str  # e.g. "category == 'BTC_5m' and price < 0.40"
    action: str  # "BUY" or "SELL"
    outcome: str  # "YES" or "NO"
    size_pct: float  # % of capital to allocate
    entry_price_target: float
    exit_profit_pct: float
    exit_loss_pct: float


@dataclass
class ReplicatedStrategy:
    """Full replicated strategy bundle ready for strategy_executor."""

    source_wallet: str = ""
    fingerprint: StrategyFingerprint = field(default_factory=StrategyFingerprint)
    rules: list[dict[str, Any]] = field(default_factory=list)
    paper_results: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0
    is_ready_for_live: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def replicate_strategy(
    source_wallet: str, our_capital: float
) -> ReplicatedStrategy:
    """Replicate a profitable wallet's strategy into executable rules.

    Steps:
    1. Fetch closed positions from wallet history.
    2. Build a strategy fingerprint.
    3. Decompose fingerprint into trading rules.
    4. Validate rules via paper simulation on historical data.
    5. Generate a strategy_executor-compatible config.
    6. Score confidence and readiness for live trading.
    """
    result = ReplicatedStrategy(source_wallet=source_wallet)

    # 1. Fetch positions
    positions = await get_all_closed_positions(source_wallet)
    if not positions:
        logger.warning("No closed positions for wallet %s", source_wallet)
        return result

    # 2. Fingerprint
    fp = strategy_fingerprint(positions)
    result.fingerprint = fp

    # 3. Decompose into rules
    rules = _decompose_rules(fp, positions)
    result.rules = [r.__dict__ for r in rules]

    # 4. Paper simulation
    paper = _simulate_paper(positions, result.rules, our_capital)
    result.paper_results = paper

    # 5. Generate config
    result.config = generate_strategy_config(fp, our_capital)

    # 6. Confidence & readiness
    result.confidence_score = _compute_replication_confidence(
        fp, paper, len(positions)
    )
    result.is_ready_for_live = (
        result.confidence_score > 0.7 and paper.get("pnl", 0) > 0
    )

    logger.info(
        "Replication complete for %s: confidence=%.2f ready=%s trades=%d pnl=%.2f",
        source_wallet,
        result.confidence_score,
        result.is_ready_for_live,
        paper.get("total_trades", 0),
        paper.get("pnl", 0),
    )
    return result


def generate_strategy_config(
    fingerprint: StrategyFingerprint, capital: float
) -> dict[str, Any]:
    """Generate a strategy_executor-compatible config dict."""
    # Position sizing: scale by confidence and strategy type
    base_size_pct = 0.05  # 5% default
    if fingerprint.size_strategy == "FIXED":
        base_size_pct = 0.04
    elif fingerprint.size_strategy == "KELLY":
        base_size_pct = 0.06

    # Max positions based on strategy type
    max_positions = 5
    if fingerprint.strategy_type == "SCALPER":
        max_positions = 10
    elif fingerprint.strategy_type == "WHALE":
        max_positions = 2

    daily_budget = capital * 0.20  # 20% of capital per day

    return {
        "name": f"replicated_{fingerprint.primary_category}",
        "category": fingerprint.primary_category,
        "entry_rules": {
            "preferred_side": fingerprint.preferred_side,
            "preferred_outcome": fingerprint.preferred_outcome,
            "avg_price_entry": fingerprint.avg_price_entry,
            "limit_order_pct": fingerprint.limit_order_pct,
        },
        "exit_rules": {
            "hold_style": fingerprint.hold_style,
            "avg_hold_time_hours": fingerprint.avg_hold_time_hours,
            "profit_factor_target": max(fingerprint.profit_factor, 1.2),
        },
        "position_sizing": {
            "mode": fingerprint.size_strategy,
            "size_pct": base_size_pct,
            "avg_size": fingerprint.avg_position_size,
        },
        "max_positions": max_positions,
        "daily_budget": daily_budget,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _decompose_rules(
    fp: StrategyFingerprint, positions: list[dict]
) -> list[Rule]:
    """Decompose fingerprint patterns into concrete trading rules."""
    rules: list[Rule] = []

    # --- Rule 1: Category preference ---
    if fp.primary_category and fp.primary_category != "Other":
        rules.append(
            Rule(
                condition=f"category == '{fp.primary_category}'",
                action="BUY" if fp.preferred_side == "BUY" else "SELL",
                outcome=fp.preferred_outcome if fp.preferred_outcome != "NEUTRAL" else "YES",
                size_pct=5.0,
                entry_price_target=fp.avg_price_entry,
                exit_profit_pct=15.0,
                exit_loss_pct=10.0,
            )
        )

    # --- Rule 2: Price entry threshold ---
    if fp.avg_price_entry > 0:
        threshold = min(fp.avg_price_entry * 1.05, 0.95)
        rules.append(
            Rule(
                condition=f"price < {threshold:.2f}",
                action="BUY",
                outcome="YES",
                size_pct=4.0,
                entry_price_target=fp.avg_price_entry,
                exit_profit_pct=12.0,
                exit_loss_pct=8.0,
            )
        )

    # --- Rule 3: Position sizing from win rate ---
    if fp.win_rate >= 0.50 and fp.profit_factor > 1.0:
        # Winner: can afford slightly larger positions
        size_pct = min(8.0, 3.0 + fp.win_rate * 10)
        exit_profit = 10.0 if fp.profit_factor > 1.5 else 12.0
        rules.append(
            Rule(
                condition="win_streak >= 2",
                action="BUY",
                outcome="YES",
                size_pct=size_pct,
                entry_price_target=fp.avg_price_entry,
                exit_profit_pct=exit_profit,
                exit_loss_pct=8.0,
            )
        )

    # --- Rule 4: Hold duration-based exit ---
    if fp.avg_hold_time_hours > 0:
        if fp.hold_style == "SCALPER":
            rules.append(
                Rule(
                    condition=f"hold_time > {max(fp.avg_hold_time_hours * 2, 0.5):.1f}h",
                    action="SELL",
                    outcome="YES",
                    size_pct=3.0,
                    entry_price_target=fp.avg_price_entry,
                    exit_profit_pct=5.0,
                    exit_loss_pct=5.0,
                )
            )
        elif fp.hold_style == "SWING":
            rules.append(
                Rule(
                    condition=f"hold_time > {fp.avg_hold_time_hours * 1.5:.0f}h",
                    action="SELL",
                    outcome="YES",
                    size_pct=4.0,
                    entry_price_target=fp.avg_price_entry,
                    exit_profit_pct=10.0,
                    exit_loss_pct=8.0,
                )
            )

    # --- Rule 5: Loss streak recovery ---
    if fp.max_consecutive_losses > 0:
        rules.append(
            Rule(
                condition=f"consecutive_losses >= {min(fp.max_consecutive_losses, 5)}",
                action="SELL",
                outcome="NO",
                size_pct=2.0,
                entry_price_target=0.0,
                exit_profit_pct=5.0,
                exit_loss_pct=3.0,
            )
        )

    return rules


def _simulate_paper(
    positions: list[dict], rules: list[dict], capital: float
) -> dict[str, Any]:
    """Replay historical positions against generated rules.

    Only counts positions that match a rule's category condition.
    Returns simulation results: total_trades, wins, losses, pnl,
    max_drawdown, win_rate.
    """
    if not positions or not rules:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "pnl": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
        }

    # Extract rule categories for matching
    rule_categories = set()
    for rule in rules:
        cond = rule.get("condition", "") if isinstance(rule, dict) else getattr(rule, "condition", "")
        if "category" in cond:
            import re
            m = re.search(r"category\s*==\s*['\"]([\w_]+)['\"]", cond)
            if m:
                cat = m.group(1)
                rule_categories.add(cat)
                # Also add base category (e.g. "BTC_5m" -> "BTC") for fuzzy matching
                base = cat.split("_")[0]
                if base != cat:
                    rule_categories.add(base)

    # Sort by timestamp for chronological replay
    sorted_positions = sorted(
        positions, key=lambda p: float(p.get("timestamp", 0))
    )

    wins = 0
    losses = 0
    total_pnl = 0.0
    equity = capital
    peak = capital
    max_drawdown = 0.0
    matched_trades = 0

    for pos in sorted_positions:
        title = pos.get("title", "")
        from backend.core.market_classifier import classify_market
        category = classify_market(title)

        # Skip positions that don't match any rule category
        # If no category rules extracted, count all positions (fallback)
        if rule_categories and category not in rule_categories:
            continue

        pnl = float(pos.get("realizedPnl", 0))
        matched_trades += 1
        total_pnl += pnl
        equity += pnl

        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

        # Track drawdown from capital
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_drawdown:
            max_drawdown = dd

    total_trades = matched_trades
    win_rate = wins / total_trades if total_trades > 0 else 0.0

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "pnl": round(total_pnl, 2),
        "max_drawdown": round(max_drawdown, 2),
        "win_rate": round(win_rate, 4),
    }


def _compute_replication_confidence(
    fp: StrategyFingerprint, paper: dict[str, Any], n_positions: int
) -> float:
    """Confidence score 0-1 based on sample size, consistency, profit factor."""
    # Component 1: sample size (0-0.4)
    if n_positions < 10:
        sample_score = 0.0
    elif n_positions < 30:
        sample_score = 0.1
    elif n_positions < 100:
        sample_score = 0.2
    elif n_positions < 300:
        sample_score = 0.3
    else:
        sample_score = 0.4

    # Component 2: consistency / low drift (0-0.3)
    consistency_score = 0.0
    if fp.win_rate >= 0.50:
        consistency_score += 0.15
    if fp.max_consecutive_losses <= 5:
        consistency_score += 0.10
    if fp.confidence >= 0.5:
        consistency_score += 0.05

    # Component 3: profit factor (0-0.3)
    pf = fp.profit_factor
    if pf >= 2.0:
        pf_score = 0.3
    elif pf >= 1.5:
        pf_score = 0.2
    elif pf >= 1.2:
        pf_score = 0.1
    else:
        pf_score = 0.0

    return min(1.0, sample_score + consistency_score + pf_score)
