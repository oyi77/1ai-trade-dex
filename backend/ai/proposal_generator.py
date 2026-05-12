"""Proposal Generator Module - Wave 4b

Generates strategy improvement proposals using Claude AI based on recent trade analysis.
Proposals are stored in the database with status 'pending_approval' and require admin approval
before execution.

This module integrates with:
- TradeAnalyzer (Wave 4a) for trade pattern analysis
- Claude API for generating improvement recommendations
- Database for proposal persistence
- API endpoints for approval workflow
"""

from loguru import logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from backend.models.database import Trade
from backend.ai.trade_analyzer import TradeAnalyzer
from backend.ai.claude import ClaudeAnalyzer
from backend.config import settings


@dataclass
class StrategyProposal:
    """Strategy improvement proposal data structure."""

    strategy_name: str
    change_type: str  # "parameter_adjustment", "threshold_change", "new_feature"
    change_details: Dict[str, Any]
    expected_impact: str
    reasoning: str
    confidence: float  # 0.0-1.0
    priority: str  # "high", "medium", "low"
    estimated_improvement: Optional[float] = None  # Expected % improvement in win rate or PnL


class ProposalGenerator:
    """Generates strategy improvement proposals based on trade analysis."""

    def __init__(self):
        """Initialize the ProposalGenerator."""
        self.logger = logger
        self.trade_analyzer = TradeAnalyzer()
        self.claude_analyzer = ClaudeAnalyzer()

    async def generate_proposal(self, recent_trades: List[Trade]) -> Optional[StrategyProposal]:
        """Generate a strategy improvement proposal from recent trades.

        Args:
            recent_trades: List of recent Trade ORM objects (typically last 20)

        Returns:
            StrategyProposal object if a valid proposal is generated, None otherwise
        """
        if not recent_trades:
            self.logger.warning("No trades provided for proposal generation")
            return None

        # Step 1: Analyze trade history to identify patterns
        self.logger.info(f"Analyzing {len(recent_trades)} recent trades")
        trade_analysis = self.trade_analyzer.analyze_trade_history(recent_trades)

        if not trade_analysis:
            self.logger.warning("Trade analysis returned empty results")
            return None

        # Step 2: Get current strategy configurations
        strategy_configs = self._get_strategy_configs()

        # Step 3: Get performance metrics
        performance_metrics = self._calculate_performance_metrics(recent_trades)

        # Step 4: Call Claude API to generate improvement proposal
        proposal = await self._generate_proposal_with_claude(
            trade_analysis=trade_analysis,
            strategy_configs=strategy_configs,
            performance_metrics=performance_metrics,
            recent_trades=recent_trades
        )

        if not proposal:
            self.logger.warning("Claude did not generate a valid proposal")
            return None

        # Step 5: Store proposal in database with status 'pending_approval'
        _db_proposal = self._store_proposal(proposal)

        self.logger.info(
            f"Generated proposal for strategy '{proposal.strategy_name}': "
            f"{proposal.change_type} (confidence={proposal.confidence:.2f})"
        )

        return proposal

    def _get_strategy_configs(self) -> Dict[str, Any]:
        """Retrieve current strategy configurations from database.

        Returns:
            Dictionary mapping strategy names to their current configurations
        """
        from backend.db.utils import get_db_session
        with get_db_session() as db:
                from backend.models.database import StrategyConfig
                configs = db.query(StrategyConfig).all()

                result = {}
                for config in configs:
                    import json
                    result[config.strategy_name] = {
                        "enabled": config.enabled,
                        "interval_seconds": config.interval_seconds,
                        "params": json.loads(config.params) if config.params else {}
                    }

                return result

    def _calculate_performance_metrics(self, trades: List[Trade]) -> Dict[str, Any]:
        """Calculate performance metrics from trades.

        Args:
            trades: List of Trade ORM objects

        Returns:
            Dictionary with performance metrics
        """
        if not trades:
            return {}

        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl and t.pnl > 0)
        losing_trades = sum(1 for t in trades if t.pnl and t.pnl <= 0)

        total_pnl = sum(t.pnl for t in trades if t.pnl is not None)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0

        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # Calculate by strategy
        strategy_performance = {}
        for trade in trades:
            if not trade.strategy:
                continue

            if trade.strategy not in strategy_performance:
                strategy_performance[trade.strategy] = {
                    "trades": 0,
                    "wins": 0,
                    "pnl": 0.0
                }

            strategy_performance[trade.strategy]["trades"] += 1
            if trade.pnl and trade.pnl > 0:
                strategy_performance[trade.strategy]["wins"] += 1
            if trade.pnl:
                strategy_performance[trade.strategy]["pnl"] += trade.pnl

        # Calculate win rates per strategy
        for strategy, perf in strategy_performance.items():
            perf["win_rate"] = perf["wins"] / perf["trades"] if perf["trades"] > 0 else 0.0

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "strategy_performance": strategy_performance
        }

    async def _generate_proposal_with_claude(
        self,
        trade_analysis: Dict[str, Any],
        strategy_configs: Dict[str, Any],
        performance_metrics: Dict[str, Any],
        recent_trades: List[Trade]
    ) -> Optional[StrategyProposal]:
        """Use Claude API to generate improvement proposal.

        Args:
            trade_analysis: Output from TradeAnalyzer.analyze_trade_history()
            strategy_configs: Current strategy configurations
            performance_metrics: Performance metrics
            recent_trades: Recent trades for context

        Returns:
            StrategyProposal object or None
        """
        # Build context for Claude
        prompt = self._build_claude_prompt(
            trade_analysis=trade_analysis,
            strategy_configs=strategy_configs,
            performance_metrics=performance_metrics,
            recent_trades=recent_trades
        )

        try:
            # Call Claude API
            client = self.claude_analyzer._get_client()

            message = await client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text

            # Parse Claude's response into a proposal
            proposal = self._parse_claude_response(response_text, performance_metrics)

            return proposal

        except Exception as e:
            self.logger.error(f"Failed to generate proposal with Claude: {e}")
            return None

    def _build_claude_prompt(
        self,
        trade_analysis: Dict[str, Any],
        strategy_configs: Dict[str, Any],
        performance_metrics: Dict[str, Any],
        recent_trades: List[Trade]
    ) -> str:
        """Build prompt for Claude API.

        Args:
            trade_analysis: Trade pattern analysis
            strategy_configs: Current strategy configurations
            performance_metrics: Performance metrics
            recent_trades: Recent trades

        Returns:
            Formatted prompt string
        """
        # Format strategy performance
        strategy_perf_text = ""
        for strategy, perf in performance_metrics.get("strategy_performance", {}).items():
            strategy_perf_text += f"\n- {strategy}: {perf['trades']} trades, {perf['win_rate']:.1%} win rate, ${perf['pnl']:.2f} PnL"

        # Format common factors
        common_wins = ", ".join(trade_analysis.get("common_win_factors", [])[:5])
        common_losses = ", ".join(trade_analysis.get("common_loss_factors", [])[:5])

        prompt = f"""You are a trading strategy optimization expert. Analyze the following trading performance data and generate ONE specific, actionable improvement proposal.

PERFORMANCE SUMMARY:
- Total trades: {performance_metrics.get('total_trades', 0)}
- Win rate: {performance_metrics.get('win_rate', 0):.1%}
- Total P&L: ${performance_metrics.get('total_pnl', 0):.2f}
- Average P&L per trade: ${performance_metrics.get('avg_pnl', 0):.2f}

STRATEGY PERFORMANCE:{strategy_perf_text}

TRADE ANALYSIS:
- Common winning factors: {common_wins or "None identified"}
- Common losing factors: {common_losses or "None identified"}
- Edge score: {trade_analysis.get('edge_score', 0):.2f}

CURRENT STRATEGY CONFIGURATIONS:
{self._format_strategy_configs(strategy_configs)}

Based on this data, generate ONE improvement proposal. Your response MUST follow this exact format:

STRATEGY: [strategy_name]
CHANGE_TYPE: [parameter_adjustment|threshold_change|new_feature]
CHANGE_DETAILS: [specific parameter changes in JSON format, e.g. {{"min_edge": 0.08, "max_position_usd": 150}}]
EXPECTED_IMPACT: [1-2 sentence description of expected improvement]
REASONING: [2-3 sentences explaining why this change will help]
CONFIDENCE: [0.0-1.0]
PRIORITY: [high|medium|low]
ESTIMATED_IMPROVEMENT: [expected % improvement in win rate or PnL, e.g. 5.0 for 5%]

Focus on:
1. Strategies with poor performance that can be improved
2. Adjusting thresholds based on common loss factors
3. Increasing position sizes for consistently winning strategies
4. Reducing exposure to strategies with high loss rates

Be specific and actionable. Do not suggest vague improvements."""

        return prompt

    def _format_strategy_configs(self, configs: Dict[str, Any]) -> str:
        """Format strategy configurations for prompt.

        Args:
            configs: Strategy configurations dictionary

        Returns:
            Formatted string
        """
        result = []
        for strategy, config in configs.items():
            import json
            params_str = json.dumps(config.get("params", {}))
            result.append(
                f"- {strategy}: enabled={config.get('enabled')}, "
                f"interval={config.get('interval_seconds')}s, params={params_str}"
            )
        return "\n".join(result)

    def _parse_claude_response(
        self,
        response_text: str,
        performance_metrics: Dict[str, Any]
    ) -> Optional[StrategyProposal]:
        """Parse Claude's response into a StrategyProposal object.

        Args:
            response_text: Raw response from Claude
            performance_metrics: Performance metrics for validation

        Returns:
            StrategyProposal object or None if parsing fails
        """
        try:
            import json
            import re

            # Extract fields using regex
            strategy_match = re.search(r"STRATEGY:\s*(.+)", response_text)
            change_type_match = re.search(r"CHANGE_TYPE:\s*(.+)", response_text)
            change_details_match = re.search(r"CHANGE_DETAILS:\s*(\{.+?\})", response_text, re.DOTALL)
            expected_impact_match = re.search(r"EXPECTED_IMPACT:\s*(.+?)(?=\n[A-Z]+:|$)", response_text, re.DOTALL)
            reasoning_match = re.search(r"REASONING:\s*(.+?)(?=\n[A-Z]+:|$)", response_text, re.DOTALL)
            confidence_match = re.search(r"CONFIDENCE:\s*([\d.]+)", response_text)
            priority_match = re.search(r"PRIORITY:\s*(.+)", response_text)
            improvement_match = re.search(r"ESTIMATED_IMPROVEMENT:\s*([\d.]+)", response_text)

            if not all([strategy_match, change_type_match, change_details_match, expected_impact_match, reasoning_match]):
                self.logger.error("Failed to parse required fields from Claude response")
                return None

            strategy_name = strategy_match.group(1).strip()
            change_type = change_type_match.group(1).strip()
            change_details_str = change_details_match.group(1).strip()
            expected_impact = expected_impact_match.group(1).strip()
            reasoning = reasoning_match.group(1).strip()
            confidence = float(confidence_match.group(1)) if confidence_match else 0.7
            priority = priority_match.group(1).strip() if priority_match else "medium"
            estimated_improvement = float(improvement_match.group(1)) if improvement_match else None

            # Parse JSON change details
            try:
                change_details = json.loads(change_details_str)
            except json.JSONDecodeError:
                self.logger.error(f"Failed to parse change_details JSON: {change_details_str}")
                return None

            # Validate change_type
            valid_change_types = ["parameter_adjustment", "threshold_change", "new_feature"]
            if change_type not in valid_change_types:
                self.logger.warning(f"Invalid change_type '{change_type}', defaulting to 'parameter_adjustment'")
                change_type = "parameter_adjustment"

            # Validate priority
            valid_priorities = ["high", "medium", "low"]
            if priority not in valid_priorities:
                priority = "medium"

            # Clamp confidence to [0, 1]
            confidence = max(0.0, min(1.0, confidence))

            return StrategyProposal(
                strategy_name=strategy_name,
                change_type=change_type,
                change_details=change_details,
                expected_impact=expected_impact,
                reasoning=reasoning,
                confidence=confidence,
                priority=priority,
                estimated_improvement=estimated_improvement
            )

        except Exception as e:
            self.logger.error(f"Failed to parse Claude response: {e}")
            self.logger.debug(f"Response text: {response_text}")
            return None

    def _store_proposal(self, proposal: StrategyProposal) -> int:
        """Store proposal in database with status 'pending_approval'.

        Args:
            proposal: StrategyProposal object

        Returns:
            Database ID of stored proposal
        """
        try:
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                    from backend.models.database import StrategyProposal as DBProposal

                    db_proposal = DBProposal(
                        strategy_name=proposal.strategy_name,
                        change_details=proposal.change_details,
                        expected_impact=proposal.expected_impact,
                        admin_decision="pending",
                        status="pending",
                        auto_promotable=proposal.change_type in ("parameter_adjustment", "threshold_change"),
                        created_at=datetime.now(timezone.utc)
                    )

                    db.add(db_proposal)
                    db.commit()
                    db.refresh(db_proposal)

                    proposal_id = db_proposal.id
                    self.logger.info(f"Stored proposal ID {proposal_id} in database")

                    return proposal_id
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to store proposal in database: {e}")
            raise

    def get_pending_proposals(self) -> List[Dict[str, Any]]:
        """Retrieve all pending proposals from database.

        Returns:
            List of proposal dictionaries
        """
        from backend.db.utils import get_db_session
        with get_db_session() as db:
                from backend.models.database import StrategyProposal as DBProposal

                proposals = db.query(DBProposal).filter(
                    DBProposal.admin_decision == "pending"
                ).order_by(DBProposal.created_at.desc()).all()

                result = []
                for p in proposals:
                    result.append({
                        "id": p.id,
                        "strategy_name": p.strategy_name,
                        "change_details": p.change_details,
                        "expected_impact": p.expected_impact,
                        "admin_decision": p.admin_decision,
                        "created_at": p.created_at.isoformat() if p.created_at else None,
                        "executed_at": p.executed_at.isoformat() if p.executed_at else None
                    })

                return result

    def approve_proposal(
        self,
        proposal_id: int,
        admin_user_id: str,
        reason: str = "Approved",
    ) -> bool:
        """Approve a proposal (requires admin).

        Args:
            proposal_id: Database ID of proposal
            admin_user_id: ID of admin user approving
            reason: Reason for approval

        Returns:
            True if approved successfully, False otherwise
        """
        try:
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                    from backend.models.database import StrategyProposal as DBProposal

                    proposal = db.query(DBProposal).filter(DBProposal.id == proposal_id).first()

                    if not proposal:
                        self.logger.error(f"Proposal {proposal_id} not found")
                        return False

                    if proposal.admin_decision != "pending":
                        self.logger.warning(f"Proposal {proposal_id} already {proposal.admin_decision}")
                        return False

                    proposal.admin_decision = "approved"
                    proposal.admin_user_id = admin_user_id
                    proposal.admin_decision_reason = reason
                    proposal.executed_at = datetime.now(timezone.utc)

                    db.commit()

                    self.logger.info(f"Proposal {proposal_id} approved by {admin_user_id}: {reason}")

                    return True
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to approve proposal {proposal_id}: {e}")
            return False

    def reject_proposal(
        self,
        proposal_id: int,
        admin_user_id: str,
        reason: str = "Rejected",
    ) -> bool:
        """Reject a proposal (requires admin).

        Args:
            proposal_id: Database ID of proposal
            admin_user_id: ID of admin user rejecting
            reason: Reason for rejection

        Returns:
            True if rejected successfully, False otherwise
        """
        try:
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                    from backend.models.database import StrategyProposal as DBProposal

                    proposal = db.query(DBProposal).filter(DBProposal.id == proposal_id).first()

                    if not proposal:
                        self.logger.error(f"Proposal {proposal_id} not found")
                        return False

                    if proposal.admin_decision != "pending":
                        self.logger.warning(f"Proposal {proposal_id} already {proposal.admin_decision}")
                        return False

                    proposal.admin_decision = "rejected"
                    proposal.admin_user_id = admin_user_id
                    proposal.admin_decision_reason = reason

                    db.commit()

                    self.logger.info(f"Proposal {proposal_id} rejected by {admin_user_id}: {reason}")

                    return True
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to reject proposal {proposal_id}: {e}")
            return False


def auto_promote_eligible_proposals():
    """Auto-deploy low-risk parameter tweak proposals. Safe for scheduled jobs.

    PIPELINE:
    1. Run forward simulation with proposed params vs baseline (current params)
    2. Gate on IMPROVEMENT over baseline, not absolute performance
    3. Apply params with adaptive deviation limit (wider for broken strategies)
    """
    try:
        from backend.models.database import StrategyProposal as DBProposal, StrategyConfig
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            eligible = db.query(DBProposal).filter(
                DBProposal.status == "pending",
                DBProposal.auto_promotable == True,
                DBProposal.backtest_passed == False,
            ).all()

            for proposal in eligible:
                try:
                    bt_result = _run_backtest_for_proposal(db, proposal)
                    proposal.backtest_sharpe = bt_result.get("sharpe", 0.0)
                    proposal.backtest_win_rate = bt_result.get("win_rate", 0.0)
                    proposal.backtest_passed = bt_result.get("passed", False)
                    db.commit()
                except (AttributeError, KeyError, ValueError) as e:
                    logger.error("Backtest failed for proposal %s: %s", proposal.id, e)
                    db.rollback()

            promotable = db.query(DBProposal).filter(
                DBProposal.status == "pending",
                DBProposal.auto_promotable == True,
                DBProposal.backtest_passed == True,
            ).all()
            for proposal in promotable:
                try:
                    config = db.query(StrategyConfig).filter(
                        StrategyConfig.strategy_name == proposal.strategy_name
                    ).first()
                    if config and proposal.change_details:
                        current_params = config.params or {}
                        if isinstance(current_params, str):
                            import json as _json
                            current_params = _json.loads(current_params)

                        baseline_wr = _get_baseline_win_rate(db, proposal.strategy_name)
                        max_deviation = 0.50 if baseline_wr < 0.20 else 0.30 if baseline_wr < 0.40 else 0.20

                        applied = False
                        for key, val in proposal.change_details.items():
                            if isinstance(val, (int, float)) and not isinstance(val, bool):
                                current_val = float(current_params.get(key, val))
                                deviation = abs(val - current_val) / max(abs(current_val), 1e-9)
                                if deviation <= max_deviation:
                                    current_params[key] = val
                                    applied = True
                                else:
                                    clamped = current_val * (1 + max_deviation * (1 if val > current_val else -1))
                                    current_params[key] = round(clamped, 6)
                                    applied = True

                        if applied:
                            import json as _json
                            config.params = _json.dumps(current_params) if not isinstance(current_params, str) else current_params
                            proposal.status = "auto_approved"
                            proposal.admin_decision = "auto_approved"
                            proposal.executed_at = datetime.now(timezone.utc)
                            db.commit()
                except (AttributeError, KeyError, ValueError) as e:
                    logger.error("Auto-promote failed for proposal %s: %s", proposal.id, e)
                    db.rollback()
    except Exception as e:
        logger.error(f"auto_promote_eligible_proposals failed: {e}", exc_info=True)


def _get_baseline_win_rate(db, strategy_name: str) -> float:
    from backend.models.database import Trade
    from sqlalchemy.sql import func
    stats = db.query(
        func.count(Trade.id).label("cnt"),
        func.count(Trade.id).filter(Trade.result == "win").label("wins"),
    ).filter(
        Trade.strategy == strategy_name,
        Trade.settled == True,
    ).first()
    cnt = stats.cnt or 0
    return (stats.wins or 0) / cnt if cnt > 0 else 0.0


def _run_backtest_for_proposal(db, proposal) -> dict:
    """Forward simulation: replay historical trades WITH proposed params applied.

    Compares simulation results against baseline (current params) to measure
    improvement. A losing strategy can pass if the proposed change IMPROVES outcomes.

    Gate: improvement in win_rate OR sharpe over baseline.
    """
    try:
        import statistics as stats_mod
        from backend.models.database import Trade

        strategy_name = proposal.strategy_name
        proposed_params = proposal.change_details or {}

        settled_trades = (
            db.query(Trade)
            .filter(Trade.strategy == strategy_name, Trade.settled == True)
            .order_by(Trade.settlement_time.asc())
            .all()
        )

        if len(settled_trades) < 3:
            return {"sharpe": 0.0, "win_rate": 0.0, "passed": False, "reason": "insufficient_data"}

        kelly_fraction = float(proposed_params.get("kelly_fraction", 0.0625))
        min_edge = float(proposed_params.get("min_edge", proposed_params.get("min_edge_threshold", 0.02)))
        max_size = float(proposed_params.get("max_trade_size", 10.0))
        slippage_buffer = float(proposed_params.get("slippage_buffer", 1.0))

        simulated_pnls = []
        baseline_pnls = []
        bankroll = 100.0

        for trade in settled_trades:
            baseline_pnls.append(trade.pnl or 0.0)

            edge = trade.edge_at_entry if hasattr(trade, 'edge_at_entry') and trade.edge_at_entry else 0.1
            if edge < min_edge:
                simulated_pnls.append(0.0)
                continue

            original_size = trade.size if hasattr(trade, 'size') and trade.size else 5.0
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
        sim_avg_pnl = stats_mod.mean(simulated_pnls) if simulated_pnls else 0.0

        sim_sharpe = 0.0
        if sim_total >= 5:
            std = stats_mod.stdev(simulated_pnls) if len(simulated_pnls) > 1 else 1.0
            sim_sharpe = sim_avg_pnl / std if std > 0 else 0.0

        base_wins = sum(1 for p in baseline_pnls if p > 0)
        base_wr = base_wins / len(baseline_pnls) if baseline_pnls else 0.0
        base_avg_pnl = stats_mod.mean(baseline_pnls) if baseline_pnls else 0.0
        base_sharpe = 0.0
        if len(baseline_pnls) >= 5:
            bstd = stats_mod.stdev(baseline_pnls) if len(baseline_pnls) > 1 else 1.0
            base_sharpe = stats_mod.mean(baseline_pnls) / bstd if bstd > 0 else 0.0

        wr_improved = sim_wr > base_wr
        pnl_improved = sim_avg_pnl > base_avg_pnl
        sharpe_improved = sim_sharpe > base_sharpe

        improvement_signals = sum([wr_improved, pnl_improved, sharpe_improved])
        passed = improvement_signals >= 2 and sim_total >= 3

        if passed:
            logger.info(
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
        logger.warning(f"Backtest failed for proposal {proposal.id}: {e}")
        return {"sharpe": 0.0, "win_rate": 0.0, "passed": False}
