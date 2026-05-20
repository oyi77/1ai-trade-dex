"""Wash trade detection for Polymarket markets."""

from dataclasses import dataclass
from enum import Enum
from collections import Counter

from loguru import logger


class WashTradeRisk(str, Enum):
    LOW = "LOW"  # score 0-25
    MEDIUM = "MEDIUM"  # score 26-50
    HIGH = "HIGH"  # score 51-75
    VERY_HIGH = "VERY_HIGH"  # score 76-100


@dataclass
class WashTradeAnalysis:
    risk: WashTradeRisk
    score: int  # 0-100
    indicators: dict[str, float]  # indicator_name -> score 0-100
    details: list[str]  # human-readable findings


class WashTradeDetector:
    WEIGHTS = {
        "self_trading": 0.30,
        "volume_liquidity_ratio": 0.20,
        "size_uniformity": 0.20,
        "timing_clustering": 0.15,
        "price_manipulation": 0.15,
    }

    def analyze_trades(
        self, trades: list[dict], market_id: str = ""
    ) -> WashTradeAnalysis:
        if not trades:
            return WashTradeAnalysis(
                risk=WashTradeRisk.LOW,
                score=0,
                indicators={k: 0.0 for k in self.WEIGHTS},
                details=["No trades to analyze"],
            )

        indicators: dict[str, float] = {}
        details: list[str] = []

        # 1. Self-trading
        st_score, st_details = self._self_trading(trades)
        indicators["self_trading"] = st_score
        details.extend(st_details)

        # 2. Volume/liquidity ratio
        vl_score, vl_details = self._volume_liquidity_ratio(trades)
        indicators["volume_liquidity_ratio"] = vl_score
        details.extend(vl_details)

        # 3. Size uniformity
        su_score, su_details = self._size_uniformity(trades)
        indicators["size_uniformity"] = su_score
        details.extend(su_details)

        # 4. Timing clustering
        tc_score, tc_details = self._timing_clustering(trades)
        indicators["timing_clustering"] = tc_score
        details.extend(tc_details)

        # 5. Price manipulation
        pm_score, pm_details = self._price_manipulation(trades)
        indicators["price_manipulation"] = pm_score
        details.extend(pm_details)

        weighted = sum(indicators[k] * w for k, w in self.WEIGHTS.items())
        score = round(weighted)

        if score <= 25:
            risk = WashTradeRisk.LOW
        elif score <= 50:
            risk = WashTradeRisk.MEDIUM
        elif score <= 75:
            risk = WashTradeRisk.HIGH
        else:
            risk = WashTradeRisk.VERY_HIGH

        if market_id:
            logger.info(
                "Wash trade analysis for %s: score=%d risk=%s",
                market_id,
                score,
                risk.value,
            )

        return WashTradeAnalysis(
            risk=risk, score=score, indicators=indicators, details=details
        )

    def _self_trading(self, trades: list[dict]) -> tuple[float, list[str]]:
        # Detect wallets that are maker AND taker within the same trade (strongest signal)
        same_trade_wallets = set()
        for t in trades:
            maker = t.get("maker", "")
            taker = t.get("taker", "")
            if maker and taker and maker == taker:
                same_trade_wallets.add(maker)

        # Also detect wallets appearing on both sides across different trades (weaker signal)
        makers = {t.get("maker", "") for t in trades if t.get("maker")}
        takers = {t.get("taker", "") for t in trades if t.get("taker")}
        cross_wallets = (makers & takers) - same_trade_wallets

        # Same-trade self-trading is heavily weighted
        count = len(same_trade_wallets) * 2 + len(cross_wallets)
        if count == 0:
            score = 0.0
            detail = []
        elif count <= 2:
            score = 50.0
            detail = [f"Self-trading: {count} wallet(s) appear on both sides"]
        else:
            score = 100.0
            detail = [
                f"Self-trading: {count} wallets appear on both maker and taker sides"
            ]

        return score, detail

    def _volume_liquidity_ratio(self, trades: list[dict]) -> tuple[float, list[str]]:
        total_volume = sum(t.get("usd_amount", 0.0) for t in trades)
        all_wallets: set[str] = set()
        for t in trades:
            maker = t.get("maker", "")
            taker = t.get("taker", "")
            if maker:
                all_wallets.add(maker)
            if taker:
                all_wallets.add(taker)

        unique_count = len(all_wallets) or 1
        ratio = total_volume / unique_count

        if ratio < 5000:
            score = 0.0
            detail = []
        elif ratio < 20000:
            score = 50.0
            detail = [f"Volume/liquidity ratio ${ratio:,.0f} per wallet (moderate)"]
        else:
            score = 100.0
            detail = [f"Volume/liquidity ratio ${ratio:,.0f} per wallet (suspicious)"]

        return score, detail

    def _size_uniformity(self, trades: list[dict]) -> tuple[float, list[str]]:
        total = len(trades)
        if total == 0:
            return 0.0, []

        rounded = [round(t.get("usd_amount", 0.0)) for t in trades]
        most_common_count = Counter(rounded).most_common(1)[0][1]
        pct = most_common_count / total

        if pct < 0.30:
            score = 0.0
            detail = []
        elif pct <= 0.60:
            score = 50.0
            detail = [f"Size uniformity: {pct:.0%} of trades share the same size"]
        else:
            score = 100.0
            detail = [
                f"Size uniformity: {pct:.0%} of trades share the same size (bot pattern)"
            ]

        return score, detail

    def _timing_clustering(self, trades: list[dict]) -> tuple[float, list[str]]:
        total = len(trades)
        if total < 2:
            return 0.0, []

        timestamps = sorted(t.get("timestamp", 0) for t in trades)
        clustered_pairs = 0
        total_pairs = total - 1

        if total_pairs <= 0:
            return 0.0, []

        for i in range(total_pairs):
            if timestamps[i + 1] - timestamps[i] <= 5:
                clustered_pairs += 1

        pct = clustered_pairs / total_pairs

        if pct < 0.20:
            score = 0.0
            detail = []
        elif pct <= 0.50:
            score = 50.0
            detail = [
                f"Timing clustering: {pct:.0%} of consecutive trade pairs within 5s"
            ]
        else:
            score = 100.0
            detail = [
                f"Timing clustering: {pct:.0%} of consecutive trade pairs within 5s (suspicious)"
            ]

        return score, detail

    def _price_manipulation(self, trades: list[dict]) -> tuple[float, list[str]]:
        total = len(trades)
        if total == 0:
            return 0.0, []

        prices = [t.get("price", 0.0) for t in trades]
        most_common_count = Counter(prices).most_common(1)[0][1]
        pct = most_common_count / total

        if pct < 0.20:
            score = 0.0
            detail = []
        elif pct <= 0.50:
            score = 50.0
            detail = [f"Price manipulation: {pct:.0%} of trades at the same price"]
        else:
            score = 100.0
            detail = [
                f"Price manipulation: {pct:.0%} of trades at identical price (suspicious)"
            ]

        return score, detail

    def get_adjusted_volume(self, raw_volume: float, wash_score: int) -> float:
        adjusted = raw_volume * (1 - wash_score / 100)
        floor = raw_volume * 0.1
        return max(adjusted, floor)
