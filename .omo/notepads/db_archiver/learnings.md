## Conventions for db_archiver.py
- Always output all required trade columns for analytics: id, market_id, market_ticker, side, size, entry_price, exit_price, pnl, result, timestamp, signal_id.
- Use pyarrow for Parquet (no pandas, no extra conversions; datetime as ISO8601 string for full tool compatibility).
- Use duckdb's parquet_scan('{parquet_path}') for ad hoc queries; in `query_parquet_analytics` the {table} placeholder is replaced directly for maximum flexibility.
- In `archive_trades_to_parquet`, market_id is set to market_ticker, as no separate field exists.
- exit_price comes from settlement_value, which is the model's post-facto close price (consistency for downstream usage).
- Output folder is makedirs-safe and handles reruns gracefully.
