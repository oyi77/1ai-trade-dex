"""Carved verbatim out of ``backend/core/wallet/bankroll_reconciliation.py`` — statements moved, no logic changed."""

from __future__ import annotations

from .bankroll_reconciliation import (
    Optional,
    dataclass,
)

from . import bankroll_reconciliation as _facade

@dataclass
class BankrollReconciliationReport:
    """One-mode reconciliation result."""

    mode: str
    source: str
    applied: bool
    old_bankroll: float
    new_bankroll: float
    old_total_pnl: float
    new_total_pnl: float
    old_trade_count: int
    new_trade_count: int
    old_win_count: int
    new_win_count: int
    open_exposure: float
    realized_pnl: float
    drift_bankroll: float
    drift_pnl: float
    pm_portfolio_value: _facade.Optional[float] = None
    warnings: list[str] = _facade.field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return (
            abs(self.drift_bankroll) > 0.01
            or abs(self.drift_pnl) > 0.01
            or self.old_trade_count != self.new_trade_count
            or self.old_win_count != self.new_win_count
        )

    def to_dict(self) -> dict:
        data = _facade.asdict(self)
        data["has_drift"] = self.has_drift
        return data
@dataclass(frozen=True)
class PolymarketProfileTradeStats:
    """Profile-level Polymarket market-count statistics."""

    traded_count: int
    closed_count: int
    winning_count: int
    losing_count: int
    open_position_count: int = 0
    stale_open_position_count: int = 0
    redeemable_position_count: int = 0
    open_position_value: float = 0.0
    open_position_initial_value: float = 0.0

    @property
    def win_rate(self) -> float:
        denominator = self.winning_count + self.losing_count
        return self.winning_count / denominator if denominator > 0 else 0.0
def get_polymarket_wallet_address() -> Optional[str]:
    """Return the wallet/proxy address used by Polymarket Data API."""

    return _facade.settings.POLYMARKET_BUILDER_ADDRESS or _facade.settings.POLYMARKET_WALLET_ADDRESS
async def fetch_pm_open_position_value(wallet: Optional[str] = None) -> Optional[float]:
    """Fetch open-position market value from Polymarket Data API.

    The /value endpoint excludes idle USDC cash, so it is not total account
    equity by itself. Total live equity is cash balance + this open value.

    Returns None on missing wallet, non-200 responses, malformed payloads, or
    transient network failures. Callers decide whether that is fatal.
    """

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{_facade.settings.DATA_API_URL}/value",
                params={"user": wallet_address.lower()},
            )
        if resp.status_code != 200:
            _facade.logger.warning(
                "PM open position value fetch returned HTTP %s for wallet %s",
                resp.status_code,
                wallet_address[:10],
            )
            return None

        data = resp.json()
        if isinstance(data, list) and data:
            value = data[0].get("value", 0)
        elif isinstance(data, dict):
            value = data.get("value", 0)
        else:
            return None

        return float(value)
    except Exception as exc:
        _facade.logger.warning("PM open position value fetch failed: %s", exc)
        return None
async def fetch_pm_portfolio_value(wallet: Optional[str] = None) -> Optional[float]:
    """Backward-compatible alias for open-position value."""

    return await fetch_pm_open_position_value(wallet)
async def fetch_pm_total_equity(wallet: Optional[str] = None) -> Optional[float]:
    """Fetch live total equity as USDC cash + PM open-position value."""

    open_value = await fetch_pm_open_position_value(wallet)
    if open_value is None:
        return None

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    cash = 0.0
    try:
        import httpx
        from backend.config import settings

        tokens = {
            "USDC.e": settings.USDC_E_ADDRESS,
            "USDC Native": settings.USDC_NATIVE_ADDRESS,
            "pUSD": settings.PUSD_ADDRESS,
        }

        rpc_url = settings.QUICKNODE_RPC_URL

        async with httpx.AsyncClient(timeout=10.0) as client:
            for name, addr in tokens.items():
                data = "0x70a08231000000000000000000000000" + wallet_address.lower()[2:]
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": addr, "data": data}, "latest"],
                    "id": 1,
                }
                try:
                    res = await client.post(
                        rpc_url,
                        json=payload,
                        headers={"User-Agent": "polyedge-finance"},
                    )
                    if res.status_code == 200 and "result" in res.json():
                        hex_val = res.json()["result"]
                        if hex_val == "0x" or not hex_val:
                            hex_val = "0x0"
                        cash += int(hex_val, 16) / 1e6
                except Exception as e:
                    _facade.logger.warning(
                        f"Failed to fetch {name} balance in reconciliation: {e}"
                    )

        _facade.logger.info(f"Total cash balance from RPC: ${cash:.2f}")
    except Exception as exc:
        _facade.logger.warning("Polygon RPC cash fetch failed, falling back to CLOB: %s", exc)
        # 2. Fallback to CLOB API if RPC fails
        try:
            from backend.data.polymarket_clob import clob_from_settings

            clob = clob_from_settings(mode="live")
            async with clob:
                await clob.create_or_derive_api_key()
                balance = await clob.get_wallet_balance()
            if balance.get("error"):
                _facade.logger.warning(
                    "CLOB cash balance fetch failed: %s", balance.get("error")
                )
                return None
            cash = float(balance.get("usdc_balance") or 0.0)
        except Exception as clob_exc:
            _facade.logger.warning("CLOB cash balance fetch failed: %s", clob_exc)
            return None

    return round(cash + float(open_value), 6)
async def _fetch_clob_pusd_balance() -> Optional[float]:
    """Fetch CLOB-internal PUSD collateral balance (tradeable cash).

    This is the ground truth for live bankroll. On-chain RPC token balances
    (USDC.e, USDC Native) include main wallet funds that are NOT in CLOB and
    cannot be traded. CLOB PUSD is what the order book actually sees.
    """
    import asyncio

    from backend.data.polymarket_clob import clob_from_settings

    try:
        clob = clob_from_settings(mode="live")
        async with clob:
            await asyncio.wait_for(clob.create_or_derive_api_key(), timeout=15.0)
            pusd = await asyncio.wait_for(clob.get_pusd_balance(), timeout=15.0)
        if pusd is not None and pusd >= 0:
            return float(pusd)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _facade.logger.warning("CLOB PUSD balance fetch failed: %s", exc)
    return None
async def fetch_pm_profile_pnl(wallet: Optional[str] = None) -> Optional[float]:
    """Fetch Polymarket profile/account PnL from the public user PnL API.

    This matches the public profile/dashboard series semantics more closely than
    the local settled-trade ledger. Returns the latest cumulative profile PnL
    point when available.
    """

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://user-pnl-api.polymarket.com/user-pnl",
                params={
                    "user_address": wallet_address.lower(),
                    "interval": "all",
                    "fidelity": "1d",
                },
                headers={"User-Agent": "polyedge-finance"},
            )

        if resp.status_code != 200:
            _facade.logger.warning(
                "PM profile PnL fetch returned HTTP %s for wallet %s",
                resp.status_code,
                wallet_address[:10],
            )
            return None

        data = resp.json()
        if not isinstance(data, list) or not data:
            return None

        latest = data[-1]
        if not isinstance(latest, dict):
            return None

        pnl_value = latest.get("p")
        if pnl_value is None:
            return None

        return round(float(pnl_value), 6)
    except Exception as exc:
        _facade.logger.warning("PM profile PnL fetch failed: %s", exc)
        return None
async def fetch_pm_traded_count(wallet: Optional[str] = None) -> Optional[int]:
    """Fetch Polymarket profile "markets traded" count for a wallet.

    Polymarket's public profile "Predictions" total is backed by the Data API
    `/traded` endpoint. This is a market/profile-level count, not equivalent to
    the local Trade ledger row count where one market/order can produce multiple
    rows across settlement, import, and strategy bookkeeping paths.
    """

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{_facade.settings.DATA_API_URL}/traded",
                params={"user": wallet_address.lower()},
                headers={"User-Agent": "polyedge-finance"},
            )

        if resp.status_code != 200:
            _facade.logger.warning(
                "PM traded-count fetch returned HTTP %s for wallet %s",
                resp.status_code,
                wallet_address[:10],
            )
            return None

        data = resp.json()
        if not isinstance(data, dict):
            return None

        traded = data.get("traded")
        if traded is None:
            return None

        return int(traded)
    except Exception as exc:
        _facade.logger.warning("PM traded-count fetch failed: %s", exc)
        return None
