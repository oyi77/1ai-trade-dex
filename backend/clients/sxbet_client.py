"""SX.bet REST + EIP-712 client."""

import os
import httpx
from eth_account import Account
from loguru import logger

from backend.core.eip712_signer import sign_typed_data

# SX.bet EIP-712 domain for Polygon (chain_id=137).
# verifyingContract: TODO — replace with the deployed SX.bet exchange contract address
# once confirmed from https://docs.sx.bet or on-chain.
_SXBET_DOMAIN = {
    "name": "SX Bet",
    "version": "2",
    "chainId": 137,
    "verifyingContract": "0xTODO_SXBET_CONTRACT_ADDRESS",  # TODO: fill from SX.bet docs
}

_SXBET_ORDER_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Order": [
        {"name": "marketHash", "type": "bytes32"},
        {"name": "outcomeIndex", "type": "uint256"},
        {"name": "odds", "type": "uint256"},
        {"name": "stakeAmount", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "expiration", "type": "uint256"},
    ],
}


class SXBetClient:
    """SX.bet API client."""

    def __init__(self, base_url: str = None):
        self._base_url = (
            base_url or os.getenv("SXBET_API_URL", "https://api.sx.bet")
        ).rstrip("/")

    async def get_sports(self) -> list:
        """Get available sports."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/sports")
            resp.raise_for_status()
            return resp.json()

    async def get_markets(self, sport_ids: list = None, limit: int = 200) -> list:
        """Get available markets, optionally filtered by sport."""
        params = {"limit": limit}
        if sport_ids:
            params["sportIds"] = ",".join(str(s) for s in sport_ids)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/markets/active", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_orderbook(self, market_hash: str) -> dict:
        """Get orderbook for a specific market."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/orders", params={"marketHashes": market_hash}
            )
            resp.raise_for_status()
            return resp.json()

    async def place_maker_order(
        self,
        market_hash: str,
        outcome_index: int,
        odds: float,
        stake_wei: int,
        private_key: str,
    ) -> dict:
        """Place a maker order with EIP-712 signature.

        Args:
            market_hash: The market identifier hash (bytes32 hex string).
            outcome_index: Which outcome to bet on (0 or 1).
            odds: Decimal odds for the order (e.g. 2.5).
            stake_wei: Stake amount in wei (USDC has 6 decimals).
            private_key: Hex private key for signing.

        Returns:
            API response dict with order details.
        """
        import time

        account = Account.from_key(private_key)

        # Convert odds to percentage-odds integer (basis points * 100)
        # SX.bet uses percentage odds in the range [1, 99] scaled to 1e20
        percentage_odds = int(odds * 1e18)

        # Expiration: 7 days from now (default maker order TTL)
        expiration = int(time.time()) + 7 * 24 * 60 * 60

        # Ensure market_hash is a bytes32 hex string
        if not market_hash.startswith("0x"):
            market_hash = f"0x{market_hash}"
        # Pad to 32 bytes if needed
        market_hash_bytes32 = market_hash.ljust(66, "0")[:66]

        message = {
            "marketHash": market_hash_bytes32,
            "outcomeIndex": outcome_index,
            "odds": percentage_odds,
            "stakeAmount": stake_wei,
            "maker": account.address,
            "expiration": expiration,
        }

        if "TODO" in _SXBET_DOMAIN["verifyingContract"]:
            raise RuntimeError(
                "SX.bet contract address not configured. "
                "Set the verifyingContract in _SXBET_DOMAIN after obtaining the "
                "deployed exchange contract from https://docs.sx.bet."
            )

        signature = sign_typed_data(
            private_key=private_key,
            domain=_SXBET_DOMAIN,
            types=_SXBET_ORDER_TYPES,
            primary_type="Order",
            message=message,
        )

        payload = {
            "marketHash": market_hash_bytes32,
            "outcomeIndex": outcome_index,
            "odds": percentage_odds,
            "stakeAmount": str(stake_wei),
            "maker": account.address,
            "expiration": expiration,
            "signature": signature,
        }

        logger.info(
            "SX.bet placing maker order",
            market_hash=market_hash_bytes32,
            outcome_index=outcome_index,
            maker=account.address,
        )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._base_url}/orders",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def health_check(self) -> bool:
        """Check if SX.bet API is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/sports")
                return resp.status_code == 200
        except Exception:
            return False
