"""Wallet watchlist store + background activity monitor.

Two responsibilities:
  (a) JSON-file-backed watchlist CRUD (add/remove/list).
  (b) Background asyncio loop that polls the tracker API for watched wallets
      and notifies the bot via ``alert_all_admins`` on new transactions.
"""

import asyncio
import json
import os
from loguru import logger
from typing import Any

from . import telegram_bot as _facade
from .tracker_client import tracker_get

_WATCH_FILE = Path(
    os.environ.get("WALLET_WATCHLIST_PATH", "data/wallet_watchlist.json")
)
_POLL_INTERVAL = int(os.environ.get("WALLET_POLL_INTERVAL", "300"))  # 5 min


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _load_watchlist() -> list[dict[str, Any]]:
    """Load watched wallets from JSON file."""
    try:
        if _WATCH_FILE.exists():
            raw = json.loads(_WATCH_FILE.read_text())
            return raw if isinstance(raw, list) else []
        return []
    except Exception as e:
        _facade.logger.warning(f"watchlist load failed: {e}")
        return []


def _save_watchlist(wallets: list[dict[str, Any]]) -> None:
    _WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WATCH_FILE.write_text(json.dumps(wallets, indent=2))


def add_wallet(address: str, chain: str = "eth", label: str = "") -> dict[str, Any]:
    """Add a wallet to the watchlist. Returns result dict with ``ok``/``msg``."""
    wallets = _load_watchlist()
    addr_lower = address.lower()
    if any(w.get("address", "").lower() == addr_lower for w in wallets):
        return {"ok": False, "msg": f"⚠️ <code>{address[:12]}…</code> already in watchlist."}
    entry: dict[str, Any] = {
        "address": address,
        "chain": chain,
        "label": label,
        "addedAt": datetime.now(timezone.utc).isoformat(),
    }
    wallets.append(entry)
    _save_watchlist(wallets)
    return {"ok": True, "msg": f"✅ Added <code>{address[:12]}…</code> [{chain}]" + (f" — {label}" if label else "")}


def remove_wallet(address: str) -> dict[str, Any]:
    """Remove a wallet from the watchlist. Returns result dict."""
    wallets = _load_watchlist()
    addr_lower = address.lower()
    before = len(wallets)
    wallets = [w for w in wallets if w.get("address", "").lower() != addr_lower]
    if len(wallets) == before:
        return {"ok": False, "msg": f"⚠️ <code>{address[:12]}…</code> not found in watchlist."}
    _save_watchlist(wallets)
    return {"ok": True, "msg": f"🗑 Removed <code>{address[:12]}…</code> from watchlist."}


def list_wallets() -> list[dict[str, Any]]:
    """Return the current watchlist."""
    return _load_watchlist()


# ---------------------------------------------------------------------------
# Background monitor
# ---------------------------------------------------------------------------

async def _monitor_loop(bot) -> None:
    """Poll tracker API for watched-wallet TXs; alert on new activity."""
    seen_hashes: dict[str, set[str]] = {}

    _facade.logger.info("[wallet-monitor] started")
    while True:
        try:
            wallets = _load_watchlist()
            for w in wallets:
                addr = w.get("address", "")
                chain = w.get("chain", "eth")
                if not addr:
                    continue

                data = await tracker_get(
                    "/api/v1/smart-money/wallet",
                    {"address": addr, "chain": chain},
                )
                if not data or not data.get("data"):
                    continue

                d = data["data"]
                recent = (d.get("recentTxs") or []) + (d.get("recentTokenTransfers") or [])
                current_hashes: set[str] = set()
                for tx in recent:
                    h = tx.get("hash") or tx.get("transactionHash") or ""
                    if h:
                        current_hashes.add(h)

                addr_key = addr.lower()
                if addr_key in seen_hashes:
                    new_hashes = current_hashes - seen_hashes[addr_key]
                    if new_hashes:
                        label = w.get("label", "")
                        label_str = f" ({label})" if label else ""
                        tx_count = d.get("txCount", 0)
                        transfer_count = d.get("tokenTransferCount", 0)
                        entity = d.get("entity") or {}
                        entity_str = f"{entity.get('label', '?')}" if entity else "Unknown"
                        text = (
                            f"🔔 <b>Wallet Activity</b>\n\n"
                            f"<code>{addr[:12]}…</code>{label_str}\n"
                            f"Entity: {entity_str}\n"
                            f"New TXs: {len(new_hashes)}\n"
                            f"Total TXs: {tx_count} | Transfers: {transfer_count}"
                        )
                        await bot.alert_all_admins(text)

                seen_hashes[addr_key] = current_hashes

        except asyncio.CancelledError:
            _facade.logger.info("[wallet-monitor] stopped")
            raise
        except Exception as e:
            _facade.logger.warning(f"[wallet-monitor] poll error: {e}")

        await asyncio.sleep(_POLL_INTERVAL)


async def start_activity_monitor(bot) -> asyncio.Task | None:
    """Start the background monitor loop. Returns the task or None."""
    if not getattr(bot, "token", "") or bot.token == "disabled":
        _facade.logger.info("[wallet-monitor] skipped — bot disabled")
        return None
    task = asyncio.create_task(_monitor_loop(bot))
    return task
