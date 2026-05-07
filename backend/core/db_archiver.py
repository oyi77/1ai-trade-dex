import os
import logging

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text

from backend.config import settings

logger = logging.getLogger(__name__)


def archive_trades_to_parquet(db_path: str, parquet_path: str, days_back: int = 1) -> int:
    engine = create_engine(f"sqlite:///{db_path}")
    since_time = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    sql = (
        "SELECT id, market_ticker AS market_id, market_ticker, direction AS side, "
        "size, entry_price, settlement_value AS exit_price, pnl, result, timestamp, signal_id "
        "FROM trades WHERE timestamp >= :since_time"
    )
    with engine.connect() as conn:
        result = conn.execute(text(sql), {"since_time": since_time})
        rows = [dict(zip(result.keys(), r)) for r in result.fetchall()]

    if not rows:
        return 0

    for row in rows:
        if isinstance(row.get("timestamp"), datetime):
            row["timestamp"] = row["timestamp"].isoformat()

    os.makedirs(os.path.dirname(os.path.abspath(parquet_path)), exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, parquet_path, compression="zstd")
    return len(rows)


def query_parquet_analytics(parquet_path: str, sql: str) -> list[dict]:
    con = duckdb.connect()
    try:
        scan = f"parquet_scan('{parquet_path}')"
        query = sql.replace("{table}", scan).replace("{parquet}", scan)
        rel = con.execute(query)
        columns = [desc[0] for desc in rel.description]
        return [dict(zip(columns, row)) for row in rel.fetchall()]
    finally:
        con.close()


def nightly_archive_job() -> None:
    raw_url = getattr(settings, "DATABASE_URL", "sqlite:///data/app.db")
    if raw_url.startswith("sqlite:///"):
        db_path = raw_url[len("sqlite:///"):]
    else:
        db_path = raw_url

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = getattr(settings, "PARQUET_DIR", "/data/parquet")
    os.makedirs(out_dir, exist_ok=True)
    parquet_path = os.path.join(out_dir, f"trades_{today}.parquet")

    count = archive_trades_to_parquet(db_path, parquet_path, days_back=1)
    logger.info("Archived %d trades → %s", count, parquet_path)

