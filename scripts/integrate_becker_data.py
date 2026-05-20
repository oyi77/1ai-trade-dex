"""Integrate Becker prediction market dataset (Parquet) for backtesting."""

import argparse
import sqlite3
import sys
from pathlib import Path

try:
    import pyarrow.parquet as pq
except ImportError:
    pq = None


def integrate(data_path: str, db_path: str = "tradingbot.db"):
    if pq is None:
        print("pyarrow not installed. Run: pip install pyarrow")
        sys.exit(1)

    data = Path(data_path)
    if not data.exists():
        print(f"Data path not found: {data_path}")
        sys.exit(1)

    parquet_files = list(data.glob("**/*.parquet"))
    if not parquet_files:
        print(f"No .parquet files found in {data_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT,
            title TEXT,
            platform TEXT,
            outcome TEXT,
            resolution_date TEXT,
            yes_final_price REAL,
            volume REAL
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT,
            timestamp TEXT,
            side TEXT,
            price REAL,
            size REAL,
            platform TEXT
        )
    """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hm_slug ON historical_markets(slug)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ht_slug ON historical_trades(market_slug)"
    )

    total_rows = 0
    for pf in parquet_files:
        table = pq.read_table(pf)
        df = table.to_pandas()
        cols = set(df.columns)

        if "slug" in cols and "outcome" in cols:
            for _, row in df.iterrows():
                conn.execute(
                    "INSERT INTO historical_markets (slug, title, platform, outcome, resolution_date, yes_final_price, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(row.get("slug", "")),
                        str(row.get("title", "")),
                        str(row.get("platform", "")),
                        str(row.get("outcome", "")),
                        str(row.get("resolution_date", "")),
                        float(row.get("yes_final_price", 0)),
                        float(row.get("volume", 0)),
                    ),
                )
                total_rows += 1

    conn.commit()
    conn.close()
    print(f"Integrated {total_rows} rows from {len(parquet_files)} parquet files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Integrate Becker dataset")
    parser.add_argument(
        "--data-path", required=True, help="Path to extracted Becker data"
    )
    parser.add_argument("--db-path", default="tradingbot.db")
    args = parser.parse_args()
    integrate(args.data_path, args.db_path)
