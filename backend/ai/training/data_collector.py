"""Collect historical resolved markets from the Polymarket Gamma API.

Each resolved market becomes a labelled ``TrainingExample`` whose label is
1.0 if the YES outcome resolved positive, 0.0 otherwise. Handles paging,
malformed rows, and network failures.
"""
from __future__ import annotations

import asyncio
import json as _json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.ai.training.feature_engineering import FeatureEngineer
from backend.config import settings

from loguru import logger
GAMMA_HOST = settings.GAMMA_API_URL


@dataclass
class TrainingExample:
    features: Dict[str, float] = field(default_factory=dict)
    label: float = 0.0
    market_id: str = ""


class DataCollector:
    """Polymarket Gamma API client that builds labelled training examples."""

    def __init__(self, page_size: int = 100, max_pages: int = 10):
        self.page_size = page_size
        self.max_pages = max_pages
        self.fe = FeatureEngineer()

    async def collect(self, lookback_days: int = 30) -> List[TrainingExample]:
        rows = await self._fetch_resolved_markets()
        examples: List[TrainingExample] = []
        for raw in rows:
            label = self._extract_label(raw)
            if label is None:
                continue
            features = self.fe.transform_one(raw)
            examples.append(
                TrainingExample(
                    features=features,
                    label=label,
                    market_id=str(raw.get("conditionId") or raw.get("id") or ""),
                )
            )
        logger.info(f"data_collector: built {len(examples)} training examples")
        return examples

    async def _fetch_resolved_markets(self) -> List[Dict[str, Any]]:
        """Page through the Gamma API for closed (resolved) markets."""
        all_rows: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for page in range(self.max_pages):
                params = {
                    "active": "false",
                    "closed": "true",
                    "limit": self.page_size,
                    "offset": page * self.page_size,
                }
                try:
                    r = await client.get(f"{GAMMA_HOST}/markets", params=params)
                    if r.status_code != 200:
                        logger.warning(
                            f"data_collector: page {page} HTTP {r.status_code}"
                        )
                        break
                    page_rows = r.json()
                    if not page_rows:
                        break
                    all_rows.extend(page_rows)
                    if len(page_rows) < self.page_size:
                        break
                except Exception as e:
                    logger.warning(f"data_collector: page {page} error: {e}")
                    break
        return all_rows

    def _extract_label(self, raw: Dict[str, Any]) -> Optional[float]:
        """Resolve the YES outcome label from a closed market row."""
        try:
            tokens = raw.get("tokens") or []
            if len(tokens) >= 1:
                yes_token = tokens[0]
                winner = yes_token.get("winner")
                if winner is True:
                    return 1.0
                if winner is False and len(tokens) > 1 and tokens[1].get("winner"):
                    return 0.0
            outcome_prices = raw.get("outcomePrices")
            if outcome_prices:
                if isinstance(outcome_prices, str):
                    outcome_prices = _json.loads(outcome_prices)
                if len(outcome_prices) >= 2:
                    return 1.0 if float(outcome_prices[0]) > 0.5 else 0.0
        except Exception as e:
            logger.debug(f"label extraction failed: {e}")
        return None


async def collect_main():
    """CLI entry point: ``python -m backend.ai.training.data_collector``."""
    from backend.core.log import configure_logging
    configure_logging()
    collector = DataCollector()
    examples = await collector.collect()
    print(f"Collected {len(examples)} training examples")


if __name__ == "__main__":
    asyncio.run(collect_main())
