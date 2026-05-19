"""
Wallet Intelligence Pipeline — Discover and replicate profitable Polymarket strategies.

Pipeline: scan -> analyze -> fingerprint -> replicate -> validate -> report
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.core.wallet_analyzer import analyze_wallet
from backend.core.wallet_resolver import resolve_wallet
from backend.core.wallet_scanner import find_profitable_traders
from backend.data.wallet_history import get_all_closed_positions
from backend.strategies.fingerprint import strategy_fingerprint
from backend.strategies.replication import replicate_strategy

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Aggregate result from a full pipeline run."""

    wallets_scanned: int = 0
    profitable_found: int = 0
    strategies_generated: int = 0
    strategies_validated: int = 0
    top_wallets: list = field(default_factory=list)
    generated_strategies: list = field(default_factory=list)
    errors: list = field(default_factory=list)


@dataclass
class WalletCandidate:
    """A single wallet that passed through the analysis pipeline."""

    wallet: str = ""
    proxy: Optional[str] = None
    pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    sharpe: float = 0.0
    strategy_type: str = ""
    confidence: float = 0.0
    copy_rating: int = 0
    rules_count: int = 0
    paper_pnl: float = 0.0
    is_viable: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_pipeline(
    min_volume: float = 1000.0,
    min_trades: int = 50,
    max_wallets: int = 20,
    min_copy_rating: int = 5,
    our_capital: float = 1000.0,
) -> PipelineResult:
    """Run the full wallet intelligence pipeline.

    Steps:
    1. Scan for profitable wallets (wallet_scanner)
    2. Analyze each candidate (wallet_analyzer)
    3. Fingerprint strategy (fingerprint)
    4. Replicate strategy (replication)
    5. Validate with paper simulation
    6. Return aggregated results
    """
    result = PipelineResult()

    # Step 1: Scan
    try:
        traders = await find_profitable_traders(
            min_volume=min_volume,
            min_trades=min_trades,
            max_results=max_wallets,
            sort_by="pnl",
        )
        result.wallets_scanned = len(traders)
        logger.info(
            "Scanned %d wallets, found %d candidates",
            result.wallets_scanned,
            len(traders),
        )
    except Exception as e:
        result.errors.append(f"Scan failed: {e}")
        logger.error("Wallet scan failed: %s", e)
        return result

    # Steps 2-5: Analyze each candidate
    for trader in traders[:max_wallets]:
        try:
            candidate = await _analyze_candidate(
                trader, our_capital, min_copy_rating
            )
            if candidate is not None:
                result.top_wallets.append(candidate)
                if candidate.is_viable:
                    result.strategies_validated += 1
                    result.generated_strategies.append(candidate)
        except Exception as e:
            result.errors.append(f"Analysis failed for {trader.wallet}: {e}")
            logger.debug("Candidate analysis failed: %s", e)

    result.profitable_found = len(result.top_wallets)
    result.strategies_generated = len(result.generated_strategies)

    logger.info(
        "Pipeline complete: %d profitable, %d validated",
        result.profitable_found,
        result.strategies_validated,
    )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _analyze_candidate(
    trader, our_capital: float, min_copy_rating: int
) -> Optional[WalletCandidate]:
    """Analyze a single wallet candidate through the full pipeline."""
    # Resolve wallet (EOA -> proxy)
    wallet_info = await resolve_wallet(trader.wallet)
    proxy = wallet_info.proxy or trader.wallet

    # Analyze performance
    analysis = await analyze_wallet(proxy, detailed=True)
    if analysis.copy_trade_rating < min_copy_rating:
        return None

    # Get positions for fingerprint
    positions = await get_all_closed_positions(proxy)
    if not positions or len(positions) < 20:
        return None

    # Fingerprint strategy
    fp = strategy_fingerprint(positions)

    # Replicate strategy
    replication = await replicate_strategy(proxy, our_capital)

    # Build candidate
    candidate = WalletCandidate(
        wallet=trader.wallet,
        proxy=proxy,
        pnl=analysis.total_pnl,
        win_rate=analysis.win_rate,
        total_trades=analysis.total_positions,
        sharpe=analysis.sharpe_ratio,
        strategy_type=fp.strategy_type,
        confidence=fp.confidence,
        copy_rating=analysis.copy_trade_rating,
        rules_count=len(replication.rules),
        paper_pnl=replication.paper_results.get("pnl", 0),
        is_viable=(
            replication.is_ready_for_live
            and replication.paper_results.get("pnl", 0) > 0
            and fp.confidence > 0.5
        ),
    )

    return candidate


def format_report(result: PipelineResult) -> str:
    """Format pipeline results as a readable report."""
    lines = [
        "=== Wallet Intelligence Pipeline Report ===",
        f"Wallets scanned: {result.wallets_scanned}",
        f"Profitable found: {result.profitable_found}",
        f"Strategies validated: {result.strategies_validated}",
        "",
    ]

    if result.top_wallets:
        lines.append("Top Candidates:")
        lines.append(
            f"{'Wallet':<15} {'PnL':>8} {'WR':>6} {'Trades':>6} "
            f"{'Sharpe':>7} {'Type':<10} {'Rating':>6} {'Viable':>6}"
        )
        lines.append("-" * 75)
        for w in sorted(result.top_wallets, key=lambda x: x.pnl, reverse=True)[
            :10
        ]:
            lines.append(
                f"{w.wallet[:13]:<15} ${w.pnl:>6.0f} {w.win_rate * 100:>5.1f}% "
                f"{w.total_trades:>5} {w.sharpe:>6.2f} {w.strategy_type:<10} "
                f"{w.copy_rating:>5}/10 {'YES' if w.is_viable else 'no':>6}"
            )

    if result.errors:
        lines.append(f"\nErrors: {len(result.errors)}")
        for e in result.errors[:5]:
            lines.append(f"  - {e}")

    return "\n".join(lines)
