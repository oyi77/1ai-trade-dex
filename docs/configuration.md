# Configuration

All settings in `backend/config.py`, overridable via environment variables.

## Database

The Polyedge bot supports multiple database backends to suit different deployment needs, from local development to production environments. SQLAlchemy 2.0 is used for ORM, providing a consistent interface across relational databases.

| Database Type | Use Case | Recommended Driver/URL Format | Notes |
|---|---|---|---|
| **SQLite** | Local development, testing, lightweight deployments | `postgresql://user:password@localhost:5432/polyedge` | Default. Simple, file-based, no external server needed. Best for getting started quickly. |
| **PostgreSQL** | Production environments, high performance, scalability, data integrity | `postgresql+psycopg2://user:password@host:5432/mydatabase` | Recommended for production due to robustness, advanced features, and strong community support. Requires `psycopg2` driver. |
| **MySQL** | Production environments, widely adopted, good performance | `mysql+pymysql://user:password@host:3306/mydatabase` | Supported for production. Requires `pymysql` driver. **Important**: It is highly recommended to use the `+pymysql` dialect in your `DATABASE_URL` for better compatibility and performance with SQLAlchemy. The application will issue a warning if `mysql://` is used without `+pymysql`. |
| **MongoDB** | Future integration | N/A | Not currently supported. Integration would require a significant architectural change, including replacing SQLAlchemy with an ODM like MongoEngine and implementing a Repository Pattern due to its non-relational nature. |

### Migration from SQLite to PostgreSQL (Zero Data Loss)

To migrate your data from SQLite (e.g., development setup) to a more robust production database like PostgreSQL using Alembic, follow these steps:

1.  **Ensure Current Schema Accuracy**: Verify that all SQLAlchemy models in `backend/models/database.py` accurately reflect your current SQLite database schema.
2.  **Generate/Update Alembic Migrations**:
    *   Ensure your Alembic environment is set up.
    *   Create an initial migration script if you haven't already: `alembic revision --autogenerate -m "Initial schema migration"`.
    *   Apply any pending migrations to your SQLite database: `alembic upgrade head`.
3.  **Dump Data from SQLite**:
    *   **Recommended (Python Script)**: Write a Python script using SQLAlchemy to connect to your SQLite database, query all data from each table, and save it to a portable format (e.g., CSV or JSON files for each table). This offers greater control over data types and transformations.
    *   *(Alternative: SQL Dump)*: Use `sqlite3 tradingbot.db .dump > sqlite_data_dump.sql`. Be aware that this dump might require manual editing for PostgreSQL compatibility (e.g., `AUTOINCREMENT` properties, data type declarations).
4.  **Create New PostgreSQL Database**:
    *   Manually create an empty PostgreSQL database on your server (e.g., `CREATE DATABASE polyedge_prod;`).
5.  **Configure Application for PostgreSQL**:
    *   Update the `DATABASE_URL` environment variable to point to your new, empty PostgreSQL database:
        `export DATABASE_URL="postgresql+psycopg2://<user>:<password>@<host>:<port>/polyedge_prod"`
6.  **Run Alembic Migrations on New Database**:
    *   Initialize the schema in the new PostgreSQL database using Alembic. This will create all tables and apply necessary constraints: `alembic upgrade head`.
7.  **Import Data into New Database**:
    *   **If using Python Script (Recommended)**: Write another Python script that connects to the new PostgreSQL database. Read data from your intermediate CSV/JSON files and use SQLAlchemy's ORM or core insert statements to re-insert the data.
    *   *(If using SQL Dump)*: Execute the carefully reviewed and edited `sqlite_data_dump.sql` on the PostgreSQL database.
8.  **Verify Data Integrity**:
    *   Thoroughly compare row counts and spot-check critical data in the PostgreSQL database against your original SQLite data.
9.  **Switch Application**:
    *   Once verified, restart your application with the `DATABASE_URL` configured for PostgreSQL.

---

## Polymarket Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `POLYMARKET_PRIVATE_KEY` | None | Wallet private key for live order placement. Never commit this value. |
| `POLYMARKET_WALLET_ADDRESS` | None | Public wallet/proxy address used to fetch live Polymarket open-position value for bankroll reconciliation. Safe to document, but set it to the wallet shown in Polymarket/CLOB. |
| `POLYMARKET_BUILDER_ADDRESS` | None | Optional Builder proxy/funder address. If present, live equity reconciliation uses this before `POLYMARKET_WALLET_ADDRESS`. |
| `POLYMARKET_SIGNATURE_TYPE` | 0 | CLOB signature type: 0 for EOA, 1 for Poly-Proxy, 2 for Poly-EOA. |
| `AUTO_REDEEM_ENABLED` | False | Enables the scheduled Polymarket redeemable-position cleanup job. |
| `AUTO_REDEEM_DRY_RUN` | True | Keeps scheduled cleanup reporting-only by default. Set to `False` only when the scheduler should submit live on-chain/relayer redemption transactions. |
| `AUTO_REDEEM_INTERVAL_SECONDS` | 3600 | Interval for the scheduled auto-redeem job. |
| `AUTO_REDEEM_TIMEOUT_SECONDS` | 120.0 | Timeout for one scheduled redemption batch. |

Live `BotState.bankroll`/`total_pnl` are derived caches. The source of truth is CLOB USDC cash plus Polymarket Data API open-position value; see `docs/architecture/adr-002-live-equity-source.md`.

## BTC Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `SCAN_INTERVAL_SECONDS` | 60 | BTC scan frequency |
| `MIN_EDGE_THRESHOLD` | 0.02 | Minimum edge (2%) |
| `MAX_ENTRY_PRICE` | 0.55 | Max entry price (55c) |
| `MAX_TRADE_SIZE` | 75.0 | Max $ per BTC trade |
| `KELLY_FRACTION` | 0.15 | Fractional Kelly multiplier |

## Kalshi Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `KALSHI_API_KEY_ID` | None | Kalshi API key ID |
| `KALSHI_PRIVATE_KEY_PATH` | None | Path to RSA private key PEM file |
| `KALSHI_ENABLED` | True | Enable/disable Kalshi market fetching |

## Weather Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `WEATHER_ENABLED` | True | Enable/disable weather trading strategies. |

---

## Prediction Market & DEX Venue Settings

PolyEdge includes a plugin-based multi-venue system supporting a wide variety of prediction markets and decentralized perpetual DEXes. These settings are read from environment variables and validated on startup. Any live venue whose required environment variables are missing will be automatically disabled.

### Shared EVM Wallet Settings
Many of the decentralized DEX venues (Aster, Lighter, Hyperliquid, Ostium) use a single shared wallet configuration, but allow for specific individual overrides.

| Setting | Default | Description |
|---------|---------|-------------|
| `WALLET_PRIVATE_KEY` | None | Primary EVM-compatible private key for CCXT swap and L2 perpetual transactions. Fallback for Aster, Lighter, Ostium, and Hyperliquid. |
| `TRADING_MODE` | `"paper"` | Bot trading mode. Set to `"live"` to enable live contract submissions, or `"paper"` to route all transactions to the safe in-memory simulator (`PaperProvider`). |

### SX.bet Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `SXBET_API_URL` | None | SX.bet prediction market API REST endpoint. |
| `SXBET_PRIVATE_KEY` | None | Private key override for EIP-712 order signing. |
| `SXBET_WALLET_ADDRESS` | None | SX.bet trading wallet public address. |

### Limitless Exchange Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `LIMITLESS_API_URL` | None | Limitless prediction market REST API endpoint. |
| `LIMITLESS_PRIVATE_KEY` | None | Private key override for Limitless Base EIP-712 signing. |
| `LIMITLESS_WALLET_ADDRESS` | None | Limitless wallet public address. |

### Myriad Markets Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `MYRIAD_API_URL` | None | Myriad prediction market REST API endpoint. |

### Azuro Protocol Settings (Bookmaker.xyz & Predict.fun)
| Setting | Default | Description |
|---------|---------|-------------|
| `AZURO_GRAPH_URL` | None | Subgraph URL for reading Gnosis/Polygon sports prediction odds. |
| `AZURO_RPC_URL` | None | JSON-RPC endpoint for smart contract interactions. |
| `AZURO_PRIVATE_KEY` | None | Private key for smart contract bet placements. |

### Ostium DEX Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `OSTIUM_RPC_URL` | None | Arbitrum JSON-RPC endpoint for contract state reads. |
| `OSTIUM_PRIVATE_KEY` | None | Private key override for Ostium perp interactions. |

### Lighter DEX Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `LIGHTER_PRIVATE_KEY` | None | Private key override for Lighter ZK-proof orders. |
| `LIGHTER_ACCOUNT_INDEX` | None | Lighter account registry index. |
| `LIGHTER_API_KEY_INDEX` | None | Lighter API key index. |

### Aster DEX Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `ASTER_PRIVATE_KEY` | None | Private key override for Aster CCXT perps signing. |
| `ASTER_WALLET_ADDRESS` | None | Aster wallet public address. |

### Hyperliquid Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `HYPERLIQUID_PRIVATE_KEY` | None | Private key override for Hyperliquid exchange API. |
| `HYPERLIQUID_WALLET_ADDRESS` | None | Hyperliquid wallet public address. |

