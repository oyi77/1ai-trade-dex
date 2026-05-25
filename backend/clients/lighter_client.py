"""Lighter DEX client using official SDK."""

import os

from lighter import AccountApi, ApiClient, Configuration, SignerClient, TransactionApi, WsClient
from loguru import logger

_LIGHTER_HOST = "https://mainnet.zklighter.elliot.ai/api/v1"


class LighterClient:
    """Lighter DEX client (zkLighter on Ethereum L2)."""

    def __init__(
        self,
        private_key: str = None,
        account_index: int = None,
        api_key_index: int = None,
        skip_signer: bool = False,
    ):
        self._private_key = private_key or os.getenv("LIGHTER_PRIVATE_KEY") or os.getenv("WALLET_PRIVATE_KEY", "")
        self._account_index = int(
            account_index or os.getenv("LIGHTER_ACCOUNT_INDEX") or "0"
        )
        self._api_key_index = int(
            api_key_index or os.getenv("LIGHTER_API_KEY_INDEX") or "2"
        )
        self._skip_signer = skip_signer
        self._initialized = False
        self._api_client = None
        self._account_api = None
        self._tx_api = None
        self._signer = None
        self._ws_client = None

    def _ensure_initialized(self):
        """Lazy-init all SDK objects (requires event loop)."""
        if self._initialized:
            return
        config = Configuration(host=_LIGHTER_HOST)
        self._api_client = ApiClient(config)
        self._account_api = AccountApi(self._api_client)
        self._tx_api = TransactionApi(self._api_client)
        if self._private_key and not self._skip_signer:
            self._signer = SignerClient(
                url=_LIGHTER_HOST,
                account_index=self._account_index,
                api_private_keys={self._api_key_index: self._private_key},
            )
        self._initialized = True

    async def get_markets(self) -> list:
        """Get all available markets."""
        self._ensure_initialized()
        return self._account_api.order_books()

    async def get_balance(self) -> dict:
        """Get account assets/balance."""
        self._ensure_initialized()
        return self._account_api.assets(account_index=self._account_index)

    async def get_positions(self) -> list:
        """Get open positions."""
        self._ensure_initialized()
        return self._account_api.positions(account_index=self._account_index)

    async def place_order(
        self,
        market_id: int,
        side: str,
        size: int,
        price: int,
        order_type: int = 0,
        time_in_force: int = 1,
    ) -> dict:
        """Place an order. Size and price are integers (use orderBookDetails for decimals).

        order_type: 0=Limit, 1=Market, 2=StopLoss, 3=StopLossLimit,
                    4=TakeProfit, 5=TakeProfitLimit, 6=TWAP
        time_in_force: 0=IOC, 1=GTT, 2=PostOnly
        """
        self._ensure_initialized()
        if not self._signer:
            raise RuntimeError("LighterClient: no private key configured for trading")

        signed_tx = self._signer.sign_create_order(
            market_id=market_id,
            side=side,
            size=size,
            price=price,
            order_type=order_type,
            time_in_force=time_in_force,
        )
        return self._tx_api.send_tx(signed_tx)

    async def cancel_order(self, market_id: int, order_id: int) -> dict:
        """Cancel an order."""
        self._ensure_initialized()
        if not self._signer:
            raise RuntimeError("LighterClient: no private key configured for trading")

        signed_tx = self._signer.sign_cancel_order(
            market_id=market_id,
            order_id=order_id,
        )
        return self._tx_api.send_tx(signed_tx)

    async def get_active_orders(self) -> list:
        """Get active orders."""
        self._ensure_initialized()
        return self._account_api.account_active_orders(
            account_index=self._account_index
        )

    async def health_check(self) -> bool:
        """Check if Lighter API is available."""
        try:
            self._ensure_initialized()
            self._account_api.info()
            return True
        except (ConnectionError, TimeoutError):
            return False

    async def watch_account(self, on_update=None):
        """Subscribe to real-time account updates (balance + positions + orders).

        Uses WsClient with account_all channel which pushes full account state on every change.
        """
        if not self._ws_client:
            self._ws_client = WsClient(
                account_ids=[self._account_index],
                on_account_update=on_update or self._default_account_handler,
            )
        await self._ws_client.run_async()

    def _default_account_handler(self, account_id, data):
        """Default handler for account updates."""
        logger.info(f"Lighter account {account_id} updated: {data}")

    async def close_ws(self):
        """Close WebSocket connection."""
        if self._ws_client:
            self._ws_client = None
