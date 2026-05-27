"""Feedback Tracker: measures whether applied proposals improved performance.

Scans recently auto-approved proposals, compares pre/post metrics from StrategyOutcome,
creates ProposalFeedback records, and rolls back changes that made things worse.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import StrategyProposal, StrategyConfig, Trade
from backend.models.outcome_tables import ProposalFeedback, ParamChange

from loguru import logger
from backend.db.utils import get_db_session
from contextlib import nullcontext
from statistics import statistics

MIN_TRADES_TO_MEASURE = 5
ROLLBACK_WR_THRESHOLD = -0.05
ROLLBACK_SHARPE_THRESHOLD = -1.0


def compute_sharpe(returns: list) -> float:
    """Compute Sharpe-like ratio (mean / stdev) with div-by-zero guards.

    Returns 0.0 for empty input, single-element input, or zero-mean inputs
    where the ratio is undefined.
    """

    if len(returns) < 2:
        return 0.0
    mean_return = statistics.mean(returns)
    if mean_return == 0:
        return 0.0
    std_return = statistics.stdev(returns)
    if std_return == 0:
        return 0.0
    return mean_return / std_return


def measure_recent_changes(db: Optional[Session] = None) -> dict:
    """Measure all recently applied proposals that haven't been measured yet."""

    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    stats = {"measured": 0, "improved": 0, "worse": 0, "rolled_back": 0}
    with ctx as db:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            proposals = (
                db.query(StrategyProposal)
                .filter(
                    StrategyProposal.admin_decision == "auto_approved",
                    StrategyProposal.executed_at.isnot(None),
                    StrategyProposal.executed_at >= cutoff,
                )
                .all()
            )

            for proposal in proposals:
                existing_fb = (
                    db.query(ProposalFeedback)
                    .filter(ProposalFeedback.proposal_id == proposal.id)
                    .first()
                )
                if existing_fb and existing_fb.measured_at is not None:
                    continue

                result = _measure_proposal(proposal, db)
                if result is None:
                    continue

                stats["measured"] += 1
                if result["improved"]:
                    stats["improved"] += 1
                else:
                    stats["worse"] += 1
                    if result.get("should_rollback", False):
                        _rollback_proposal(proposal, db)
                        stats["rolled_back"] += 1

            db.commit()
            return stats
        except Exception as e:
            logger.error("[FeedbackTracker] measure failed: %s", e)
            if owns_db:
                db.rollback()
            return stats


def _measure_proposal(proposal: StrategyProposal, db: Session) -> Optional[dict]:
    strategy = proposal.strategy_name
    applied_at = proposal.executed_at
    if not applied_at:
        return None

    pre_trades = (
        db.query(Trade)
        .filter(
            Trade.strategy == strategy,
            Trade.settled,
            Trade.timestamp < applied_at,
        )
        .order_by(Trade.timestamp.desc())
        .limit(50)
        .all()
    )

    post_trades = (
        db.query(Trade)
        .filter(
            Trade.strategy == strategy,
            Trade.settled,
            Trade.timestamp >= applied_at,
        )
        .order_by(Trade.timestamp.asc())
        .limit(50)
        .all()
    )

    if len(post_trades) < MIN_TRADES_TO_MEASURE:
        return None

    pre_wr = (
        sum(1 for t in pre_trades if t.result == "win") / len(pre_trades)
        if pre_trades
        else 0.0
    )
    post_wr = sum(1 for t in post_trades if t.result == "win") / len(post_trades)
    pre_pnl = sum(t.pnl or 0.0 for t in pre_trades)
    post_pnl = sum(t.pnl or 0.0 for t in post_trades)

    pre_pnls = [t.pnl or 0.0 for t in pre_trades]
    post_pnls = [t.pnl or 0.0 for t in post_trades]

    pre_stdev = statistics.stdev(pre_pnls) if len(pre_pnls) > 1 else 0.0
    post_stdev = statistics.stdev(post_pnls) if len(post_pnls) > 1 else 0.0
    pre_sharpe = statistics.mean(pre_pnls) / pre_stdev if pre_stdev > 0 else 0.0
    post_sharpe = statistics.mean(post_pnls) / post_stdev if post_stdev > 0 else 0.0

    wr_improved = post_wr > pre_wr
    pnl_improved = post_pnl > pre_pnl
    sharpe_improved = post_sharpe > pre_sharpe
    improved = sum([wr_improved, pnl_improved, sharpe_improved]) >= 2

    fb = (
        db.query(ProposalFeedback)
        .filter(ProposalFeedback.proposal_id == proposal.id)
        .first()
    )

    if not fb:
        fb = ProposalFeedback(
            proposal_id=proposal.id,
            strategy=strategy,
            change_type="parameter_adjustment",
            params_changed=proposal.change_details,
        )
        db.add(fb)

    fb.pre_wr = pre_wr
    fb.pre_sharpe = pre_sharpe
    fb.pre_pnl = pre_pnl
    fb.post_wr = post_wr
    fb.post_sharpe = post_sharpe
    fb.post_pnl = post_pnl
    fb.improved = improved
    fb.measured_at = datetime.now(timezone.utc)
    fb.measurement_trades = len(post_trades)

    should_rollback = (post_wr - pre_wr) < ROLLBACK_WR_THRESHOLD or (
        post_sharpe - pre_sharpe
    ) < ROLLBACK_SHARPE_THRESHOLD

    if improved:
        logger.info(
            "[FeedbackTracker] Proposal #%d IMPROVED %s: wr %.1f→%.1f, sharpe %.2f→%.2f",
            proposal.id,
            strategy,
            pre_wr,
            post_wr,
            pre_sharpe,
            post_sharpe,
        )
    else:
        logger.warning(
            "[FeedbackTracker] Proposal #%d WORSENED %s: wr %.1f→%.1f, sharpe %.2f→%.2f",
            proposal.id,
            strategy,
            pre_wr,
            post_wr,
            pre_sharpe,
            post_sharpe,
        )

    return {"improved": improved, "should_rollback": should_rollback}


def _rollback_proposal(proposal: StrategyProposal, db: Session) -> None:
    strategy = proposal.strategy_name
    config = (
        db.query(StrategyConfig)
        .filter(StrategyConfig.strategy_name == strategy)
        .first()
    )
    if not config or not proposal.change_details:
        return

    current_params = config.params or {}
    if isinstance(current_params, str):
        current_params = json.loads(current_params)

    rolled_back = {}
    for key, val in proposal.change_details.items():
        if (
            key in current_params
            and isinstance(val, (int, float))
            and not isinstance(val, bool)
        ):
            rolled_back[key] = {"was": current_params[key], "removed": val}
            del current_params[key]

    if rolled_back:
        config.params = (
            json.dumps(current_params)
            if not isinstance(current_params, str)
            else current_params
        )
        proposal.admin_decision = "rolled_back"
        proposal.status = "rolled_back"

        db.add(
            ParamChange(
                strategy=strategy,
                param_name="rollback",
                old_value=0,
                new_value=0,
                reasoning=f"Rolled back proposal #{proposal.id}: {list(rolled_back.keys())}",
                applied_at=datetime.now(timezone.utc),
                auto_applied=True,
            )
        )

        logger.warning(
            "[FeedbackTracker] ROLLED BACK proposal #%d for %s: removed %s",
            proposal.id,
            strategy,
            list(rolled_back.keys()),
        )
