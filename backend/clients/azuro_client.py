"""Azuro Protocol GraphQL + Web3 client."""

import os
import time
import httpx
from loguru import logger


class AzuroClient:
    """Azuro Protocol client for querying markets and placing bets on Azuro-powered venues."""

    DEFAULT_GRAPH_URL = (
        "https://thegraph.azuro.org/subgraphs/name/azuro-protocol/azuro-api-gnosis-v3"
    )

    def __init__(
        self, graph_url: str = None, rpc_url: str = None, chain_id: int = None
    ):
        from backend.config import settings
        self._graph_url = graph_url or getattr(settings, "AZURO_GRAPH_URL", self.DEFAULT_GRAPH_URL)
        self._rpc_url = rpc_url or getattr(settings, "AZURO_RPC_URL", "https://rpc.gnosischain.com")
        self._chain_id = chain_id or int(getattr(settings, "AZURO_CHAIN_ID", 100))
        self._cache: dict = {}
        self._cache_ttl = int(getattr(settings, "AZURO_CACHE_TTL_SECONDS", 60))

    async def cached_query(self, gql: str, variables: dict = None) -> dict:
        """Execute GraphQL query with caching."""
        key = (gql, str(variables))
        now = time.time()
        if key in self._cache and now - self._cache[key]["ts"] < self._cache_ttl:
            return self._cache[key]["data"]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self._graph_url, json={"query": gql, "variables": variables or {}}
            )
            resp.raise_for_status()
            data = resp.json()
        self._cache[key] = {"data": data, "ts": now}
        return data

    async def get_markets(self, limit: int = 200, active_only: bool = True) -> list:
        """Query Azuro subgraph for markets."""
        gql = """query GetMarkets($limit: Int) { conditions(first: $limit) { conditionId outcomes { outcomeId title currentValue } } }"""
        result = await self.cached_query(gql, {"limit": limit})
        return result.get("data", {}).get("conditions", [])

    async def health_check(self) -> bool:
        """Check if Azuro GraphQL endpoint is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._graph_url, json={"query": "{ __typename }"}
                )
                return resp.status_code == 200
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            return False

    async def sign_and_send_bet(
        self, private_key: str, condition_id: str, outcome_index: int, amount_wei: int
    ) -> str:
        """Sign and send a bet via Web3.py contract call on Gnosis chain.

        Azuro Protocol (used by Bookmaker.xyz, Predict.fun) uses an LP
        contract to accept bets.  The ABI and address must be configured
        via environment variables:

            AZURO_LP_ADDRESS   — deployed LP contract address on Gnosis
            AZURO_LP_ABI_PATH  — path to the JSON ABI file

        Args:
            private_key: Hex private key (funded with xDAI on Gnosis).
            condition_id: The Azuro condition identifier (from subgraph).
            outcome_index: Index of the outcome to bet on.
            amount_wei: Bet amount in wei (xDAI is 18 decimals).

        Returns:
            Transaction hash of the submitted bet.
        """
        try:
            from web3 import Web3
            from eth_account import Account
        except ImportError:
            raise RuntimeError(
                "web3 and eth_account packages required for Azuro live betting. "
                "Install with: pip install web3 eth_account"
            )

        from backend.config import settings
        lp_address = getattr(settings, "AZURO_LP_ADDRESS", None) or os.getenv("AZURO_LP_ADDRESS")
        lp_abi_path = getattr(settings, "AZURO_LP_ABI_PATH", None) or os.getenv("AZURO_LP_ABI_PATH")

        if not lp_address or not lp_abi_path:
            raise RuntimeError(
                "Azuro LP contract not configured. Set these environment variables:\n"
                "  AZURO_LP_ADDRESS  — LP contract address on Gnosis (xDai)\n"
                "  AZURO_LP_ABI_PATH — path to the LP contract ABI JSON file\n\n"
                "To obtain the ABI:\n"
                "  1. Find the LP address from https://docs.azuro.org or the Azuro subgraph\n"
                "  2. Verify on https://gnosisscan.io and copy the ABI\n"
                "  3. Save as a JSON file and set AZURO_LP_ABI_PATH to its path"
            )

        import json
        import pathlib

        abi_file = pathlib.Path(lp_abi_path)
        if not abi_file.exists():
            raise RuntimeError(f"Azuro LP ABI file not found at: {lp_abi_path}")

        with open(abi_file) as f:
            lp_abi = json.load(f)

        w3 = Web3(Web3.HTTPProvider(self._rpc_url))
        if not w3.is_connected():
            raise RuntimeError(f"Cannot connect to Gnosis RPC at {self._rpc_url}")

        account = Account.from_key(private_key)
        lp_contract = w3.eth.contract(
            address=Web3.to_checksum_address(lp_address), abi=lp_abi
        )

        logger.info(
            "Azuro placing bet",
            condition_id=condition_id,
            outcome_index=outcome_index,
            amount_wei=amount_wei,
            bettor=account.address,
        )

        # Build the bet transaction.
        # Azuro LP contracts accept bets via `makeBet` or similar method.
        # The exact method name depends on LP version — try common variants.
        try:
            tx = lp_contract.functions.makeBet(
                condition_id,
                outcome_index,
                amount_wei,
            ).build_transaction(
                {
                    "from": account.address,
                    "value": amount_wei,  # xDAI bets use native currency
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "gas": 500_000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": self._chain_id,
                }
            )
        except Exception:
            # Fallback: try `bet` method name (older Azuro LP versions)
            try:
                tx = lp_contract.functions.bet(
                    condition_id,
                    outcome_index,
                    amount_wei,
                ).build_transaction(
                    {
                        "from": account.address,
                        "value": amount_wei,
                        "nonce": w3.eth.get_transaction_count(account.address),
                        "gas": 500_000,
                        "gasPrice": w3.eth.gas_price,
                        "chainId": self._chain_id,
                    }
                )
            except Exception as build_err:
                raise RuntimeError(
                    f"Failed to build Azuro bet transaction. The ABI may not contain "
                    f"'makeBet' or 'bet' methods. Error: {build_err}"
                )

        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        logger.info("Azuro bet submitted", tx_hash=tx_hash.hex())
        return tx_hash.hex()

    async def get_balance(self, wallet_address: str = None) -> dict:
        """Get xDAI/USDC balance for a wallet on Gnosis chain.

        Returns dict with 'balance' (xDAI as float) and 'raw_wei'.
        """
        from backend.config import settings
        addr = wallet_address or getattr(settings, "AZURO_WALLET_ADDRESS", "") or ""
        if not addr:
            return {"balance": 0.0, "raw_wei": 0}
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(self._rpc_url))
            if not w3.is_connected():
                logger.warning("[azuro] Cannot connect to RPC for balance check")
                return {"balance": 0.0, "raw_wei": 0}
            checksum = Web3.to_checksum_address(addr)
            balance_wei = w3.eth.get_balance(checksum)
            balance_xdai = float(w3.from_wei(balance_wei, "ether"))
            return {"balance": balance_xdai, "raw_wei": balance_wei}
        except Exception as e:
            logger.warning(f"[azuro] get_balance error: {e}")
            return {"balance": 0.0, "raw_wei": 0}
