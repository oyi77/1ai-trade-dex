"""Trade Analyzer Module - Wave 4a

Analyzes existing trades to identify patterns, winners/losers, and insights
that feed into proposal generation for the Self-Improvement Engine.

This module provides deterministic analysis based on trade data from the database,
without external API calls or LLM integration (that comes in Wave 4b).
"""

import logging
from typing import Dict, Any, List

from backend.models import database as db_mod
from backend.models.database import Trade

logger = logging.getLogger(__name__)


class TradeAnalyzer:
    """Analyzes trades to extract patterns and insights."""

    def __init__(self):
        """Initialize the TradeAnalyzer."""
        self.logger = logging.getLogger(__name__)
        self._session_factory = db_mod.SessionLocal

    def analyze_trade(self, trade_id: int) -> Dict[str, Any]:
        """Analyze a single trade by ID.

        Args:
            trade_id: Database ID of the trade to analyze

        Returns:
            Dictionary containing:
                - trade_id: int
                - pnl: float
                - why_profitable: str (if PnL > 0)
                - why_unprofitable: str (if PnL <= 0)
                - key_factors: List[str]
                - edge: float (0.0-1.0)
                - confidence: float (0.0-1.0)

            Returns None if trade not found.
        """
        db = self._session_factory()
        try:
            trade = db.query(Trade).filter(Trade.id == trade_id).first()

            if not trade:
                self.logger.warning(f"Trade {trade_id} not found")
                return None

            # Handle missing data gracefully
            if trade.entry_price is None:
                self.logger.warning(
                    f"Trade {trade_id} missing entry_price, skipping"
                )
                return None

            # Handle zero quantity edge case
            if trade.size == 0 or trade.size is None:
                self.logger.warning(f"Trade {trade_id} has zero or null quantity")
                return {
                    "trade_id": trade_id,
                    "pnl": 0.0,
                    "why_unprofitable": "Zero quantity trade - no position taken",
                    "key_factors": ["zero_quantity"],
                    "edge": 0.0,
                    "confidence": 1.0,
                }

            # Calculate PnL
            pnl = self._calculate_pnl(trade)

            # Determine profitability and analyze
            if pnl > 0:
                analysis = self._analyze_profitable_trade(trade, pnl)
            else:
                analysis = self._analyze_unprofitable_trade(trade, pnl)

            analysis["trade_id"] = trade_id
            analysis["pnl"] = pnl

            self.logger.info(
                f"Analyzed trade {trade_id}: PnL={pnl:.2f}, "
                f"confidence={analysis['confidence']:.2f}"
            )

            return analysis

        finally:
            db.close()

    def analyze_trade_history(self, trades: List[Trade]) -> Dict[str, Any]:
        """Analyze multiple trades to identify patterns.

        Args:
            trades: List of Trade ORM objects

        Returns:
            Dictionary containing:
                - total_trades: int
                - winning_trades: int
                - losing_trades: int
                - win_rate: float
                - avg_win: float
                - avg_loss: float
                - common_win_factors: List[str]
                - common_loss_factors: List[str]
                - edge_score: float

            Returns {} if trades list is empty.
        """
        # Edge case: empty trade list
        if not trades:
            self.logger.info("Empty trade list provided, returning empty dict")
            return {}

        winning_trades = []
        losing_trades = []
        all_win_factors = []
        all_loss_factors = []
        all_edges = []

        for trade in trades:
            # Skip trades with missing data
            if (trade.entry_price is None or
                trade.size is None or
                trade.size == 0):
                self.logger.warning(f"Skipping trade {trade.id} due to missing data")
                continue

            pnl = self._calculate_pnl(trade)

            if pnl > 0:
                winning_trades.append(pnl)
                analysis = self._analyze_profitable_trade(trade, pnl)
                all_win_factors.extend(analysis["key_factors"])
                all_edges.append(analysis["edge"])
            else:
                losing_trades.append(pnl)
                analysis = self._analyze_unprofitable_trade(trade, pnl)
                all_loss_factors.extend(analysis["key_factors"])
                all_edges.append(analysis["edge"])

        total_trades = len(winning_trades) + len(losing_trades)

        # Edge case: no valid trades after filtering
        if total_trades == 0:
            self.logger.warning("No valid trades after filtering")
            return {}

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
        avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0.0
        avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0.0
        edge_score = sum(all_edges) / len(all_edges) if all_edges else 0.0

        # Identify common factors
        common_win_factors = self._get_common_factors(all_win_factors)
        common_loss_factors = self._get_common_factors(all_loss_factors)

        # Check for outliers
        outliers = self._detect_outliers(winning_trades + losing_trades)
        if outliers:
            self.logger.info(f"Detected {len(outliers)} outlier trades")

        result = {
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "common_win_factors": common_win_factors,
            "common_loss_factors": common_loss_factors,
            "edge_score": edge_score,
        }

        self.logger.info(
            f"Analyzed {total_trades} trades: win_rate={win_rate:.2%}, "
            f"edge_score={edge_score:.2f}"
        )

        return result

    def _calculate_pnl(self, trade: Trade) -> float:
        """Calculate PnL for a trade.

        For prediction markets:
        - If direction is "up" and settlement_value is 1.0, we win
        - If direction is "down" and settlement_value is 0.0, we win
        - PnL = (settlement_value - entry_price) * size for "up" direction
        - PnL = (entry_price - settlement_value) * size for "down" direction

        Args:
            trade: Trade ORM object

        Returns:
            PnL as float
        """
        # Use stored PnL if available
        if trade.pnl is not None:
            return trade.pnl

        # Calculate from settlement value
        if trade.settlement_value is None:
            # Trade not settled yet, estimate based on result
            if trade.result == "win":
                return abs(trade.entry_price - 1.0) * trade.size if trade.direction == "up" else abs(trade.entry_price) * trade.size
            elif trade.result == "loss":
                return -trade.entry_price * trade.size if trade.direction == "up" else -(1.0 - trade.entry_price) * trade.size
            else:
                return 0.0

        # Calculate based on direction and settlement
        if trade.direction == "up":
            pnl = (trade.settlement_value - trade.entry_price) * trade.size
        else:
            pnl = (trade.entry_price - trade.settlement_value) * trade.size

        return pnl

    def _analyze_profitable_trade(self, trade: Trade, pnl: float) -> Dict[str, Any]:
        """Analyze why a trade was profitable.

        Args:
            trade: Trade ORM object
            pnl: Calculated PnL

        Returns:
            Analysis dictionary with why_profitable, key_factors, edge, confidence
        """
        key_factors = []
        reasons = []

        # Analyze entry timing
        if trade.entry_price and trade.market_price_at_entry:
            if trade.entry_price < trade.market_price_at_entry:
                key_factors.append("good_entry_price")
                reasons.append("favorable entry price below market")

        # Analyze confidence
        if trade.confidence and trade.confidence > 0.7:
            key_factors.append("high_confidence_signal")
            reasons.append("high confidence signal")

        # Analyze edge
        if trade.edge_at_entry and trade.edge_at_entry > 0.1:
            key_factors.append("strong_edge")
            reasons.append("strong edge at entry")

        # Analyze strategy
        if trade.strategy:
            key_factors.append(f"strategy_{trade.strategy}")
            reasons.append(f"strategy: {trade.strategy}")

        # Analyze model probability
        if trade.model_probability and trade.model_probability > 0.6:
            key_factors.append("high_model_probability")
            reasons.append("high model probability")

        # Default if no specific factors identified
        if not reasons:
            reasons.append("favorable market movement")
            key_factors.append("market_direction")

        why_profitable = "Profitable due to: " + ", ".join(reasons)

        # Calculate edge score (0.0-1.0)
        edge = trade.edge_at_entry if trade.edge_at_entry else 0.5
        edge = max(0.0, min(1.0, edge))  # Clamp to [0, 1]

        # Calculate confidence (0.0-1.0)
        confidence = trade.confidence if trade.confidence else 0.7
        confidence = max(0.0, min(1.0, confidence))

        return {
            "why_profitable": why_profitable,
            "key_factors": key_factors,
            "edge": edge,
            "confidence": confidence,
        }

    def _analyze_unprofitable_trade(self, trade: Trade, pnl: float) -> Dict[str, Any]:
        """Analyze why a trade was unprofitable.

        Args:
            trade: Trade ORM object
            pnl: Calculated PnL

        Returns:
            Analysis dictionary with why_unprofitable, key_factors, edge, confidence
        """
        key_factors = []
        reasons = []

        # Analyze entry timing
        if trade.entry_price and trade.market_price_at_entry:
            if trade.entry_price > trade.market_price_at_entry:
                key_factors.append("poor_entry_price")
                reasons.append("unfavorable entry price above market")

        # Analyze confidence
        if trade.confidence and trade.confidence < 0.5:
            key_factors.append("low_confidence_signal")
            reasons.append("low confidence signal")

        # Analyze edge
        if trade.edge_at_entry and trade.edge_at_entry < 0.05:
            key_factors.append("weak_edge")
            reasons.append("weak edge at entry")

        # Analyze slippage
        if trade.slippage and trade.slippage > 0.02:
            key_factors.append("high_slippage")
            reasons.append("high slippage")

        # Analyze fees
        if trade.fee and trade.fee > pnl * 0.5:
            key_factors.append("high_fees")
            reasons.append("fees eroded profit")

        # Analyze strategy
        if trade.strategy:
            key_factors.append(f"strategy_{trade.strategy}")

        # Default if no specific factors identified
        if not reasons:
            reasons.append("adverse market movement")
            key_factors.append("market_reversal")

        why_unprofitable = "Unprofitable due to: " + ", ".join(reasons)

        # Calculate edge score (lower for losing trades)
        edge = trade.edge_at_entry if trade.edge_at_entry else 0.3
        edge = max(0.0, min(1.0, edge))

        # Calculate confidence (lower for losing trades)
        confidence = trade.confidence if trade.confidence else 0.5
        confidence = max(0.0, min(1.0, confidence))

        return {
            "why_unprofitable": why_unprofitable,
            "key_factors": key_factors,
            "edge": edge,
            "confidence": confidence,
        }

    def _get_common_factors(self, factors: List[str]) -> List[str]:
        """Identify most common factors from a list.

        Args:
            factors: List of factor strings

        Returns:
            List of factors that appear more than once, sorted by frequency
        """
        if not factors:
            return []

        from collections import Counter
        factor_counts = Counter(factors)

        # Return factors that appear more than once, sorted by frequency
        common = [
            factor for factor, count in factor_counts.most_common()
            if count > 1
        ]

        return common[:5]  # Top 5 most common

    def _detect_outliers(self, pnls: List[float]) -> List[int]:
        """Detect outlier trades (PnL > 10x median).

        Args:
            pnls: List of PnL values

        Returns:
            List of indices of outlier trades
        """
        if len(pnls) < 3:
            return []

        # Calculate median
        sorted_pnls = sorted([abs(p) for p in pnls])
        median_idx = len(sorted_pnls) // 2
        median = sorted_pnls[median_idx]

        if median == 0:
            return []

        # Find outliers (10x median)
        outliers = []
        for i, pnl in enumerate(pnls):
            if abs(pnl) > median * 10:
                outliers.append(i)
                self.logger.info(
                    f"Outlier detected at index {i}: PnL={pnl:.2f} "
                    f"(median={median:.2f})"
                )

        return outliers
