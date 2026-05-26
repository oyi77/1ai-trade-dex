import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text

import duckdb
import pyarrow as pa
import pyarrow.dataset as ds
from loguru import logger

from backend.config import settings


def archive_trades_to_parquet(
    db_path: str, parquet_dir: str, days_back: int = 1
) -> int:
    """Archive settled trades from SQLite to partitioned Parquet files.

    Folders will be structured as:
    parquet_dir/strategy={strategy}/year={year}/month={month}/
    """
    engine = create_engine(f"sqlite:///{db_path}")
    since_time = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    sql = (
        "SELECT id, market_ticker AS market_id, market_ticker, direction AS side, "
        "size, entry_price, settlement_value AS exit_price, pnl, result, timestamp, "
        "signal_id, strategy, COALESCE(role, 'unknown') AS role, market_type AS category "
        "FROM trades WHERE timestamp >= :since_time"
    )
    with engine.connect() as conn:
        result = conn.execute(text(sql), {"since_time": since_time})
        rows = [dict(zip(result.keys(), r)) for r in result.fetchall()]

    if not rows:
        return 0

    # Ensure date parsing and string alignment
    for row in rows:
        ts = row.get("timestamp")
        dt = None
        if isinstance(ts, datetime):
            dt = ts
        elif isinstance(ts, str):
            try:
                clean_ts = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
                dt = datetime.fromisoformat(clean_ts)
            except Exception:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        row["timestamp"] = dt.isoformat()
        row["year"] = str(dt.year)
        row["month"] = f"{dt.month:02d}"

        if not row.get("strategy"):
            row["strategy"] = "unknown"

    os.makedirs(parquet_dir, exist_ok=True)
    table = pa.Table.from_pylist(rows)

    # Use explicit Hive partitioning schema to generate strategy={strategy}/ etc. folders
    hive_partition = ds.partitioning(
        pa.schema([
            ("strategy", pa.string()),
            ("year", pa.string()),
            ("month", pa.string()),
        ]),
        flavor="hive"
    )

    # Write as partitioned hive dataset
    ds.write_dataset(
        table,
        base_dir=parquet_dir,
        format="parquet",
        partitioning=hive_partition,
        existing_data_behavior="overwrite_or_ignore",
    )
    return len(rows)


def query_parquet_analytics(parquet_path: str, sql: str) -> list[dict]:
    """Execute SQL query over Parquet files using DuckDB.

    Supports both single parquet files and partitioned directories.
    """
    con = duckdb.connect()
    try:
        if os.path.isdir(parquet_path):
            scan_path = os.path.join(parquet_path, "**/*.parquet")
            scan = f"read_parquet('{scan_path}', hive_partitioning=True)"
        else:
            scan = f"read_parquet('{parquet_path}')"

        query = sql.replace("{table}", scan).replace("{parquet}", scan)
        rel = con.execute(query)
        columns = [desc[0] for desc in rel.description]
        return [dict(zip(columns, row)) for row in rel.fetchall()]
    finally:
        con.close()


def nightly_archive_job() -> None:
    raw_url = getattr(settings, "DATABASE_URL", "sqlite:///data/app.db")
    if raw_url.startswith("sqlite:///"):
        db_path = raw_url[len("sqlite:///") :]
    else:
        db_path = raw_url

    out_dir = getattr(settings, "PARQUET_DIR", "/data/parquet")
    # Archive into partitioned trades folder inside out_dir
    parquet_dir = os.path.join(out_dir, "trades")

    count = archive_trades_to_parquet(db_path, parquet_dir, days_back=1)
    logger.info("Archived %d trades to partitioned Parquet → %s", count, parquet_dir)
