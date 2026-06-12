"""Test suite for LighterClient.get_balance()."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def client():
    with patch.dict(os.environ, {"WALLET_PRIVATE_KEY": "0x" + "aa" * 32}, clear=False):
        from backend.clients.lighter_client import LighterClient

        c = LighterClient(skip_signer=True)
        c._initialized = True
        c._account_api = MagicMock()
        return c


@pytest.mark.asyncio
async def test_get_balance_finds_usdc(client):
    usdc_acc = MagicMock()
    usdc_acc.symbol = "USDC"
    usdc_acc.balance = "1234.56"

    eth_acc = MagicMock()
    eth_acc.symbol = "ETH"
    eth_acc.balance = "5"

    result = MagicMock()
    result.accounts = [eth_acc, usdc_acc]
    client._account_api.account = AsyncMock(return_value=result)

    bal = await client.get_balance()

    assert bal == {"usdc": 1234.56, "total": 1234.56}
    client._account_api.account.assert_called_once_with(by="index", value="0")


@pytest.mark.asyncio
async def test_get_balance_no_usdc_account(client):
    eth_acc = MagicMock()
    eth_acc.symbol = "ETH"
    eth_acc.balance = "5"

    result = MagicMock()
    result.accounts = [eth_acc]
    client._account_api.account = AsyncMock(return_value=result)

    bal = await client.get_balance()

    assert bal == {"usdc": 0.0, "total": 0.0}


@pytest.mark.asyncio
async def test_get_balance_empty_accounts(client):
    result = MagicMock()
    result.accounts = []
    client._account_api.account = AsyncMock(return_value=result)

    bal = await client.get_balance()

    assert bal == {"usdc": 0.0, "total": 0.0}
