"""Carved verbatim out of ``backend/ai/proposal_generator.py`` — statements moved, no logic changed."""

from . import proposal_generator as _facade

def _get_baseline_win_rate(db, strategy_name: str) -> float:

    stats = (
        db.query(
            _facade.func.count(_facade.Trade.id).label("cnt"),
            _facade.func.count(_facade.Trade.id).filter(_facade.Trade.result == "win").label("wins"),
        )
        .filter(
            _facade.Trade.strategy == strategy_name,
            _facade.Trade.settled,
        )
        .first()
    )
    cnt = stats.cnt or 0
    return (stats.wins or 0) / cnt if cnt > 0 else 0.0
def _run_backtest_for_proposal(db, proposal) -> dict:
    """⚠️ PnL REPLAY, NOT A REAL BACKTEST.

    This is NOT a true backtest that re-runs the strategy on historical data.
    Instead, it REPLAYS existing settled Trade PnLs with proposed parameters
    applied as scaling factors:
    - Filters trades by min_edge
    - Scales sizes using kelly_fraction * edge
    - Applies slippage_buffer multiplier

    This is a fast "what-if" simulation, not a genuine strategy re-execution.
    Results show how proposed parameter changes would have scaled EXISTING trade outcomes.

    Compares replay results against baseline (current params) to measure
    improvement. A losing strategy can pass if the proposed change IMPROVES outcomes.

    Gate: improvement in win_rate OR sharpe over baseline (≥2 of 3 metrics + ≥3 trades).
    """
    try:

        # ⚠️ IMPORTANT: This is PnL replay, NOT a real backtest
        _facade.logger.warning(
            f"Proposal {proposal.id}: Running PnL REPLAY (not real backtest). "
            f"Scaling existing trade outcomes by proposed params, not re-executing strategy."
        )

        strategy_name = proposal.strategy_name
        proposed_params = proposal.change_details or {}

        settled_trades = (
            db.query(_facade.Trade)
            .filter(_facade.Trade.strategy == strategy_name, _facade.Trade.settled)
            .order_by(_facade.Trade.settlement_time.asc())
            .all()
        )

        if len(settled_trades) < 3:
            return {
                "sharpe": 0.0,
                "win_rate": 0.0,
                "passed": False,
                "reason": "insufficient_data",
            }

        kelly_fraction = float(proposed_params.get("kelly_fraction", 0.0625))
        min_edge = float(
            proposed_params.get(
                "min_edge", proposed_params.get("min_edge_threshold", 0.02)
            )
        )
        max_size = float(proposed_params.get("max_trade_size", 10.0))
        slippage_buffer = float(proposed_params.get("slippage_buffer", 1.0))

        simulated_pnls = []
        baseline_pnls = []
        bankroll = 100.0

        for trade in settled_trades:
            baseline_pnls.append(trade.pnl or 0.0)

            edge = (
                trade.edge_at_entry
                if hasattr(trade, "edge_at_entry") and trade.edge_at_entry
                else 0.1
            )
            if edge < min_edge:
                simulated_pnls.append(0.0)
                continue

            original_size = trade.size if hasattr(trade, "size") and trade.size else 5.0
            proposed_size = min(bankroll * kelly_fraction * edge, max_size)
            proposed_size = max(proposed_size, 1.0)

            size_ratio = proposed_size / max(original_size, 0.01)
            original_pnl = trade.pnl or 0.0

            adjusted_pnl = original_pnl * size_ratio
            if slippage_buffer != 1.0:
                adjusted_pnl *= slippage_buffer

            simulated_pnls.append(adjusted_pnl)
            bankroll += adjusted_pnl

        sim_wins = sum(1 for p in simulated_pnls if p > 0)
        sim_total = len(simulated_pnls)
        sim_wr = sim_wins / sim_total if sim_total > 0 else 0.0
        sim_avg_pnl = _facade.stats_mod.mean(simulated_pnls) if simulated_pnls else 0.0

        sim_sharpe = 0.0
        if sim_total >= 5:
            std = _facade.stats_mod.stdev(simulated_pnls) if len(simulated_pnls) > 1 else 1.0
            sim_sharpe = sim_avg_pnl / std if std > 0 else 0.0

        base_wins = sum(1 for p in baseline_pnls if p > 0)
        base_wr = base_wins / len(baseline_pnls) if baseline_pnls else 0.0
        base_avg_pnl = _facade.stats_mod.mean(baseline_pnls) if baseline_pnls else 0.0
        base_sharpe = 0.0
        if len(baseline_pnls) >= 5:
            bstd = _facade.stats_mod.stdev(baseline_pnls) if len(baseline_pnls) > 1 else 1.0
            base_sharpe = _facade.stats_mod.mean(baseline_pnls) / bstd if bstd > 0 else 0.0

        wr_improved = sim_wr > base_wr
        pnl_improved = sim_avg_pnl > base_avg_pnl
        sharpe_improved = sim_sharpe > base_sharpe

        improvement_signals = sum([wr_improved, pnl_improved, sharpe_improved])
        passed = improvement_signals >= 2 and sim_total >= 3

        if passed:
            _facade.logger.info(
                f"Proposal {proposal.id} PASSED: sim_wr={sim_wr:.1%} vs base={base_wr:.1%}, "
                f"sim_sharpe={sim_sharpe:.2f} vs base={base_sharpe:.2f}, "
                f"sim_avg_pnl=${sim_avg_pnl:.2f} vs base=${base_avg_pnl:.2f}"
            )

        return {
            "sharpe": round(sim_sharpe, 4),
            "win_rate": round(sim_wr, 4),
            "passed": passed,
            "baseline_win_rate": round(base_wr, 4),
            "baseline_sharpe": round(base_sharpe, 4),
        }
    except Exception as e:
        _facade.logger.warning(f"Backtest failed for proposal {proposal.id}: {e}")
        return {"sharpe": 0.0, "win_rate": 0.0, "passed": False}
def auto_promote_eligible_proposals():
    """Auto-deploy low-risk parameter tweak proposals. Safe for scheduled jobs.

    PIPELINE:
    1. Run forward simulation with proposed params vs baseline (current params)
    2. Gate on IMPROVEMENT over baseline, not absolute performance
    3. Apply params with adaptive deviation limit (wider for broken strategies)
    """
    try:
        with _facade.get_db_session() as db:
            eligible = (
                db.query(_facade.DBProposal)
                .filter(
                    _facade.DBProposal.admin_decision == "pending",
                    _facade.DBProposal.auto_promotable,
                    not _facade.DBProposal.backtest_passed,
                )
                .all()
            )

            for proposal in eligible:
                try:
                    bt_result = _run_backtest_for_proposal(db, proposal)
                    proposal.backtest_sharpe = bt_result.get("sharpe", 0.0)
                    proposal.backtest_win_rate = bt_result.get("win_rate", 0.0)
                    proposal.backtest_passed = bt_result.get("passed", False)
                    db.commit()
                except (AttributeError, KeyError, ValueError) as e:
                    _facade.logger.error("Backtest failed for proposal %s: %s", proposal.id, e)
                    db.rollback()

            promotable = (
                db.query(_facade.DBProposal)
                .filter(
                    _facade.DBProposal.admin_decision == "pending",
                    _facade.DBProposal.auto_promotable,
                    _facade.DBProposal.backtest_passed,
                )
                .all()
            )
            for proposal in promotable:
                try:
                    config = (
                        db.query(_facade.StrategyConfig)
                        .filter(_facade.StrategyConfig.strategy_name == proposal.strategy_name)
                        .first()
                    )
                    if config and proposal.change_details:
                        current_params = config.params or {}
                        if isinstance(current_params, str):

                            current_params = _facade.json.loads(current_params)

                        baseline_wr = _get_baseline_win_rate(db, proposal.strategy_name)
                        max_deviation = (
                            0.50
                            if baseline_wr < 0.20
                            else 0.30 if baseline_wr < 0.40 else 0.20
                        )

                        applied = False
                        for key, val in proposal.change_details.items():
                            if isinstance(val, (int, float)) and not isinstance(
                                val, bool
                            ):
                                current_val = float(current_params.get(key, val))
                                deviation = abs(val - current_val) / max(
                                    abs(current_val), 1e-9
                                )
                                if deviation <= max_deviation:
                                    current_params[key] = val
                                    applied = True
                                else:
                                    clamped = current_val * (
                                        1
                                        + max_deviation
                                        * (1 if val > current_val else -1)
                                    )
                                    current_params[key] = round(clamped, 6)
                                    applied = True

                        if applied:

                            config.params = (
                                _facade.json.dumps(current_params)
                                if not isinstance(current_params, str)
                                else current_params
                            )
                            proposal.status = "auto_approved"
                            proposal.admin_decision = "auto_approved"
                            proposal.executed_at = _facade.datetime.now(_facade.timezone.utc)
                            db.commit()
                except (AttributeError, KeyError, ValueError) as e:
                    _facade.logger.error(
                        "Auto-promote failed for proposal %s: %s", proposal.id, e
                    )
                    db.rollback()
    except Exception as e:
        _facade.logger.error(f"auto_promote_eligible_proposals failed: {e}", exc_info=True)
