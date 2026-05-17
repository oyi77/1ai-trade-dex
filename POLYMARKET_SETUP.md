# Polymarket Setup Guide

## Quick Start (Single Private Key)

**You only need ONE credential:** `POLYMARKET_PRIVATE_KEY`

1. Get your wallet private key from MetaMask or your Ethereum wallet
2. Set `POLYMARKET_PRIVATE_KEY` in your `.env` file
3. Start the bot — API keys are **automatically derived** from your private key

```bash
# .env file - only this ONE line is required
POLYMARKET_PRIVATE_KEY=0x1234567890abcdef...
```

## How It Works

The bot uses `py-clob-client` with automatic API key derivation:

```
Private Key → EIP-712 Signature → API Key Creation
```

1. Your private key signs an EIP-712 message
2. Polymarket API creates API credentials (api_key, api_secret, api_passphrase)
3. Credentials are cached for subsequent requests

## Optional: Pre-Derived Credentials

If you already have Polymarket API credentials from [polymarket.com/api-keys](https://polymarket.com/api-keys), you can skip derivation:

```bash
POLYMARKET_PRIVATE_KEY=0x1234567890abcdef...
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_API_PASSPHRASE=your_passphrase
```

## Trading Modes

| Mode | Description | Credentials |
|------|-------------|-------------|
| **Paper** | Simulated trading, no real money | None required |
| **Testnet** | Testnet trading with fake USDC | `POLYMARKET_PRIVATE_KEY` only |
| **Live** | Real trading on Polymarket | `POLYMARKET_PRIVATE_KEY` only (auto-derives) |

## Security Notes

- **NEVER commit your `.env` file** to git
- **NEVER share your private key** with anyone
- The private key is used for EIP-712 signing only — never transmitted
- Auto-derived API credentials are stored in memory only

## Troubleshooting

**"API key derivation failed"**
- Ensure your private key is valid hex (0x-prefixed, 64 hex chars)
- Check you're on the correct network (Polygon mainnet for live)

**"Invalid API credentials"**
- If using pre-derived credentials, verify they match your Polymarket account
- Try removing pre-derived credentials to force re-derivation

## References

- [py-clob-client Documentation](https://github.com/Polymarket/py-clob-client)
- [Polymarket API Keys](https://polymarket.com/api-keys)
- [EIP-712 Typed Data](https://eips.ethereum.org/EIPS/eip-712)


## Current Status (May 2026)

### CLOB Connection
- ✅ CLOB Auth working (API key derivation fixed)
- ✅ Wallet: `0xAd85C2F3942561AFA448cbbD5811a5f7E2e3C6Bd`
- ✅ Builder Program enabled (gasless trading)
- ⚠️ Balance: approximately $1,600 available

### Settlement
- ✅ Settlement via Gamma API using condition_id
- ✅ Paper trades also resolved via Gamma
- ✅ 470+ previously unresolved trades backfilled

Risk layer auto-disables any strategy exceeding loss limits.
