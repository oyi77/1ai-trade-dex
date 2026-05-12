"""Dynamic whale discovery — seeds candidates and computes scores."""
from typing import List

from backend.models.database import WalletConfig
from backend.core.whale_scoring import calculate_whale_score
from backend.config import settings

from loguru import logger
class WhaleDiscovery:
    async def discover(self, min_trades: int = 10) -> List[dict]:
        """
        Compute whale scores for all WalletConfig rows that have enough trade history.
        Persists score back into WalletConfig.whale_score.

        Returns: list of {wallet, score, trade_count} dicts ordered by score desc.
        """
        results = []
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            wallets = db.query(WalletConfig).all()
            for w in wallets:
                history = await self._fetch_history(w.address)
                if len(history) < min_trades:
                    continue
                days = self._estimate_days(history)
                score = calculate_whale_score(history, days_active=days)
                w.whale_score = score
                results.append(
                    {
                        "wallet": w.address,
                        "score": score,
                        "trade_count": len(history),
                    }
                )
            db.commit()
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    async def _fetch_history(self, wallet: str) -> List[dict]:
        """Fetch the wallet's recent positions from the Polymarket Data API.

        Returns a list of trade dicts compatible with calculate_whale_score:
        ``[{"pnl": float, "size": float, "timestamp": int}, ...]``.
        Network or parse failures return an empty list (whale gets score 0).
        """
        if not wallet:
            return []
        url = f"{settings.DATA_API_URL}/positions?user={wallet}&limit=200"
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
            if r.status_code != 200:
                return []
            payload = r.json()
            rows = payload if isinstance(payload, list) else payload.get("data", [])
            out: List[dict] = []
            for row in rows:
                try:
                    out.append(
                        {
                            "pnl": float(
                                row.get("realizedPnl", row.get("pnl", 0.0)) or 0.0
                            ),
                            "size": float(
                                row.get("size", row.get("initialValue", 0.0)) or 0.0
                            ),
                            "timestamp": int(
                                row.get("timestamp", row.get("createdAt", 0)) or 0
                            ),
                        }
                    )
                except Exception as e:
                    logger.debug(f"Failed to parse position row for {wallet}: {e}")
                    continue
            return out
        except Exception as e:
            logger.debug(f"polymarket data api fetch failed for {wallet}: {e}")
            return []

    def _estimate_days(self, history: List[dict]) -> float:
        if not history:
            return 1.0
        try:
            timestamps = [h.get("timestamp") for h in history if h.get("timestamp")]
            if not timestamps:
                return 1.0
            spread = max(timestamps) - min(timestamps)
            return max(spread / 86400.0, 1.0)
        except Exception as e:
            logger.debug(f"Failed to estimate days from history: {e}")
            return 1.0
