"""Trade Archiver — archives settled trades to Parquet for fast analytical queries."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("trading_bot.parquet_archiver")

DATA_DIR = Path("data/trades")


class TradeArchiver:
    """Archive settled trades to Parquet files and run analytical queries."""

    def archive_trades(self, db, date: Optional[datetime] = None) -> Optional[str]:
        date = date or datetime.now(timezone.utc)
        path = DATA_DIR / f"{date.strftime('%Y-%m-%d')}.parquet"

        try:
            import pandas as pd
        except ImportError:
            logger.warning("pandas not installed — Parquet archival skipped")
            return None

        from backend.models.database import Trade
        from sqlalchemy import func

        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        from sqlalchemy import and_

        trades = db.query(Trade).filter(
            and_(
                Trade.settled == True,
                Trade.timestamp >= start,
                Trade.timestamp < start.replace(day=start.day + 1) if start.day < 28 else start,
            )
        ).all()

        if not trades:
            logger.debug(f"No settled trades to archive for {date.date()}")
            return None

        rows = []
        for t in trades:
            rows.append({
                "id": t.id,
                "market_ticker": getattr(t, "market_ticker", ""),
                "direction": getattr(t, "direction", ""),
                "strategy": getattr(t, "strategy", ""),
                "entry_price": getattr(t, "entry_price", 0.0),
                "size": getattr(t, "size", 0.0),
                "pnl": getattr(t, "pnl", 0.0),
                "result": getattr(t, "result", ""),
                "confidence": getattr(t, "confidence", 0.0),
                "platform": getattr(t, "platform", ""),
                "role": getattr(t, "role", "unknown"),
                "timestamp": t.timestamp.isoformat() if t.timestamp else "",
            })

        df = pd.DataFrame(rows)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(str(path), compression="snappy", index=False)
        logger.info(f"Archived {len(rows)} trades to {path}")
        return str(path)

    def query_backtest(self, pattern: str = "2026-*", sql_condition: str = "1=1") -> Optional[object]:
        try:
            import pandas as pd
        except ImportError:
            logger.warning("pandas not installed — query_backtest unavailable")
            return None

        glob_path = DATA_DIR / f"{pattern}.parquet"
        files = sorted(Path(str(glob_path)).parent.glob(Path(str(glob_path)).name))

        if not files:
            logger.debug(f"No Parquet files matching {pattern}")
            return None

        dfs = [pd.read_parquet(str(f)) for f in files]
        combined = pd.concat(dfs, ignore_index=True)

        try:
            result = combined.query(sql_condition)
        except Exception as e:
            logger.warning(f"Query failed: {e}")
            return combined

        return result
