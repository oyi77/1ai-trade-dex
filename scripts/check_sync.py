#!/usr/bin/env python3
"""Check local DB vs Polymarket sync status."""
import asyncio, os, sys, json, httpx
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

url = os.getenv('DATABASE_URL')
engine = create_engine(url)

# ── 1. DB Bot State ──
print("=" * 60)
print("1. LOCAL DB - BOT STATE")
print("=" * 60)
with engine.connect() as conn:
    cols = [r[0] for r in conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name='bot_state' ORDER BY ordinal_position")
    ).fetchall()]
    rows = conn.execute(text("SELECT * FROM bot_state")).fetchall()
    for row in rows:
        for i, col in enumerate(cols):
            val = row[i] if i < len(row) else None
            if val is not None:
                print(f"  {col}: {val}")

# ── 2. DB Trade counts ──
print()
print("=" * 60)
print("2. LOCAL DB - TRADE COUNTS")
print("=" * 60)
with engine.connect() as conn:
    for mode in ('live', 'paper'):
        r = conn.execute(text(
            "SELECT status, COUNT(*) as cnt, ROUND(COALESCE(SUM(size),0)::numeric,2) as total_size, "
            "ROUND(COALESCE(SUM(pnl),0)::numeric,4) as total_pnl "
            "FROM trades WHERE trading_mode=:m GROUP BY status ORDER BY status"
        ), {'m': mode}).fetchall()
        print(f"\n  {mode}:")
        for row in r:
            st = str(row[0] or 'None')
            print(f"    status={st:<16} cnt={row[1]:>5} size={row[2]:>10} pnl={row[3]:>10}")

# ── 3. DB Unsettled live trades detail ──
with engine.connect() as conn:
    r = conn.execute(text(
        "SELECT strategy, direction, market_ticker, ROUND(size::numeric,2), ROUND(COALESCE(pnl,0)::numeric,2), "
        "status, clob_order_id, timestamp "
        "FROM trades WHERE trading_mode='live' AND status IS NULL "
        "ORDER BY timestamp DESC LIMIT 20"
    )).fetchall()
    print()
    print("=" * 60)
    print("3. LOCAL DB - UNSETTLED LIVE (latest 20)")
    print("=" * 60)
    for row in r:
        print(f"  {row[0]:<20} {row[1]:<5} sz=${row[3]} pnl=${row[4]} st={row[5]} mkt={(row[2] or '?')[:35]} ts={row[7]}")

    # by date
    r2 = conn.execute(text(
        "SELECT DATE(timestamp) as dt, COUNT(*), ROUND(SUM(size)::numeric,2) "
        "from trades WHERE trading_mode='live' AND status IS NULL "
        "GROUP BY DATE(timestamp) ORDER BY dt DESC LIMIT 10"
    )).fetchall()
    print("\n  By date:")
    for row in r2:
        print(f"    {row[0]}: {row[1]} trades, ${row[2]}")

# ── 4. Polymarket Data API (positions + value) ──
print()
print("=" * 60)
print("4. POLYMARKET - DATA API")
print("=" * 60)
wallet = os.getenv('POLYMARKET_WALLET_ADDRESS', '').lower()

async def fetch_data_api():
    async with httpx.AsyncClient(timeout=15) as client:
        # Portfolio value
        r = await client.get(f'https://data-api.polymarket.com/portfolio/value?user={wallet}')
        print(f"\n  Portfolio value: {r.status_code}")
        if r.status_code == 200:
            print(f"    {json.dumps(r.json(), indent=2)}")

        # Positions
        r = await client.get(f'https://data-api.polymarket.com/positions?user={wallet}')
        print(f"\n  Positions: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, list), type(data)
            print(f"    Count: {len(data)}")
            total_val = 0
            for p in data:
                title = (p.get('title') or p.get('conditionId') or '?')[:50]
                size = float(p.get('size', 0))
                cur_price = float(p.get('curPrice', 0) or 0)
                val = size * cur_price
                total_val += val
                if size > 0:
                    print(f"    {title}: size={size} price={cur_price:.4f} val=${val:.2f} outcome={p.get('outcome','?')}")
            print(f"    TOTAL positions value: ${total_val:.2f}")

asyncio.run(fetch_data_api())

# ── 5. CLOB API balance + recent trades ──
print()
print("=" * 60)
print("5. POLYMARKET - CLOB API")
print("=" * 60)

async def check_clob():
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams

    key = os.getenv('POLYMARKET_PRIVATE_KEY')
    creds = ApiCreds(
        api_key=os.getenv('POLYMARKET_API_KEY'),
        api_secret=os.getenv('POLYMARKET_API_SECRET'),
        api_passphrase=os.getenv('POLYMARKET_API_PASSPHRASE')
    )
    client = ClobClient('https://clob.polymarket.com', key=key, chain_id=137, creds=creds)

    # Balance
    bal = client.get_balance_allowance(BalanceAllowanceParams(asset_type='COLLATERAL'))
    print(f"  PUSD balance: {bal.get('balance', '?')}")
    print(f"  Allowances: {bal.get('allowances', {})}")

    # Recent trades
    trades = client.get_trades()
    print(f"\n  CLOB trades total: {len(trades) if trades else 0}")
    if trades:
        print("  Latest 10:")
        for t in trades[:10]:
            mkt = str(t.get('market', '?'))[:45]
            side = t.get('side', '?')
            size = t.get('size', '?')
            price = t.get('price', '?')
            status = t.get('status', '?')
            print(f"    {mkt} | {side} | sz={size} | px={price} | {status}")

asyncio.run(check_clob())

# ── 6. On-chain balances ──
print()
print("=" * 60)
print("6. ON-CHAIN - WALLET BALANCES")
print("=" * 60)
from web3 import Web3
rpc_url = os.getenv('POLYGON_RPC_URL', '') or 'https://polygon-rpc.com'
w3 = Web3(Web3.HTTPProvider(rpc_url))
proxy = os.getenv('POLYMARKET_WALLET_ADDRESS')
main = os.getenv('POLYMARKET_RELAYER_API_KEY_ADDRESS')

usdc_e = Web3.to_checksum_address('0x2791Bca1f2de4661DD883A7d955d1CfC4B1917a6')
usdc = Web3.to_checksum_address('0x3c499c542cEF5E3811e1192ce70d8cC03d0B5890')
abi_bal = [{'constant':True,'inputs':[{'name':'o','type':'address'}],'name':'balanceOf','outputs':[{'name':'b','type':'uint256'}],'type':'function'},
           {'constant':True,'inputs':[],'name':'decimals','outputs':[{'name':'','type':'uint8'}],'type':'function'}]

for label, caddr, waddr in [
    ('USDC.e proxy', usdc_e, proxy),
    ('USDC.e main', usdc_e, main),
    ('USDC proxy', usdc, proxy),
    ('USDC main', usdc, main),
]:
    contract = w3.eth.contract(address=caddr, abi=abi_bal)
    dec = contract.functions.decimals().call()
    bal = contract.functions.balanceOf(Web3.to_checksum_address(waddr)).call()
    print(f"  {label}: ${bal / (10**dec):.4f}")

# MATIC
for label, waddr in [('MATIC proxy', proxy), ('MATIC main', main)]:
    bal = w3.eth.get_balance(Web3.to_checksum_address(waddr))
    print(f"  {label}: {w3.from_wei(bal, 'ether'):.4f} MATIC")

print()
print("=" * 60)
print("DONE - Summary above")
print("=" * 60)
