"""Bitget Wallet Web3 provider implementations.

Each module is auto-imported to trigger the ``@get_registry().plugin``
decorator at startup.
"""

from backend.data.bitget_wallet.providers.api_provider import BitgetWalletAPIProvider  # noqa: F401
