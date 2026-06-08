"""Trust Wallet Agent Kit (TWAK) client for BNB HACK hackathon.

Wraps the TWAK CLI as a Python client for programmatic access to:
- Wallet management (create, balance, portfolio)
- Trading (swap, quote, DCA, limit orders)
- Market data (price, token info, risk scores)
- x402 payments
- Automation (alerts, triggers)

TWAK operates in two modes:
  Mode A - Agent Wallet: Dedicated wallet, autonomous within rules
  Mode B - WalletConnect: User-in-the-loop, per-transaction approval

For the hackathon Track 1 (Autonomous Trading Agents), we use Mode A.
The TWAK CLI is installed via: curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Default TWAK binary path
_TWAK_BIN = os.getenv("TWAK_BIN", "twak")


@dataclass
class TWAKConfig:
    """TWAK client configuration."""
    access_id: str = field(default_factory=lambda: os.getenv("TWAK_ACCESS_ID", ""))
    hmac_secret: str = field(default_factory=lambda: os.getenv("TWAK_HMAC_SECRET", ""))
    wallet_password: str = field(default_factory=lambda: os.getenv("TWAK_WALLET_PASSWORD", ""))
    autonomous_mode: bool = True
    default_chain: str = "bsc"
    twak_bin: str = _TWAK_BIN


class TWAKClient:
    """Python wrapper around TWAK CLI for agentic trading.

    Usage:
        client = TWAKClient(TWAKConfig())
        price = await client.get_price("ETH")
        result = await client.swap("100", "USDC", "ETH", quote_only=True)
    """

    _paper_positions: Dict[str, "TWAKClient.PaperPosition"] = {}
    _paper_balance: float = 10000.0

    def __init__(self, config: Optional[TWAKConfig] = None):
        self.config = config or TWAKConfig()
        self._initialized = False
        self._paper_positions = {}
        self._paper_balance = 10000.0

    async def _run(self, *args: str, timeout: float = 30.0) -> Dict[str, Any]:
        """Run a TWAK CLI command and parse JSON output.

        Args:
            *args: CLI arguments (e.g. "price", "ETH")
            timeout: Command timeout in seconds

        Returns:
            Parsed JSON response
        """
        cmd = [self.config.twak_bin, *args, "--json"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "TWAK_ACCESS_ID": self.config.access_id,
                    "TWAK_HMAC_SECRET": self.config.hmac_secret,
                },
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            if proc.returncode != 0:
                err = stderr.decode().strip()
                logger.error(f"TWAK command failed: {' '.join(cmd)} — {err}")
                return {"error": err, "success": False}

            output = stdout.decode().strip()
            if not output:
                return {"success": True}

            try:
                return json.loads(output)
            except json.JSONDecodeError:
                # Some TWAK commands return plain text
                return {"output": output, "success": True}

        except asyncio.TimeoutError:
            logger.error(f"TWAK command timed out: {' '.join(cmd)}")
            return {"error": "timeout", "success": False}
        except FileNotFoundError:
            logger.error(
                f"TWAK CLI not found at {self.config.twak_bin}. "
                "Install: curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash"
            )
            return {"error": "twak_not_installed", "success": False}

    # ------------------------------------------------------------------
    # Wallet & Identity
    # ------------------------------------------------------------------

    async def wallet_info(self) -> Dict[str, Any]:
        """Get wallet information and balances across all chains."""
        return await self._run("wallet", "info")

    async def wallet_portfolio(self) -> Dict[str, Any]:
        """Get portfolio summary across all chains."""
        return await self._run("wallet", "portfolio")

    async def wallet_balance(self, chain: Optional[str] = None) -> Dict[str, Any]:
        """Get wallet balance for a specific chain."""
        args = ["wallet", "balance"]
        if chain:
            args.extend(["--chain", chain])
        if self.config.wallet_password:
            args.extend(["--password", self.config.wallet_password])
        return await self._run(*args)

    async def wallet_create(self) -> Dict[str, Any]:
        """Create a new agent wallet."""
        return await self._run("wallet", "create")

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    async def get_price(self, token: str) -> Dict[str, Any]:
        """Get current price for a token."""
        return await self._run("price", token)

    async def get_token_info(self, token: str) -> Dict[str, Any]:
        """Get detailed token information including risk score."""
        return await self._run("token", "info", token)

    # ------------------------------------------------------------------
    # Trading & Swap
    # ------------------------------------------------------------------

    async def swap(
        self,
        amount: str,
        from_token: str,
        to_token: str,
        chain: Optional[str] = None,
        quote_only: bool = True,
        slippage: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute or quote a cross-chain swap.

        Args:
            amount: Amount of from_token (e.g. "100")
            from_token: Source token symbol (e.g. "USDC")
            to_token: Destination token symbol (e.g. "ETH")
            chain: Chain to execute on (defaults to config.default_chain)
            quote_only: If True, only get a quote without executing
        """
        args = ["swap", amount, from_token, to_token]
        args.extend(["--chain", chain or self.config.default_chain])
        if slippage:
            args.extend(["--slippage", slippage])
        if self.config.wallet_password:
            args.extend(["--password", self.config.wallet_password])
        if quote_only:
            args.append("--quote-only")
        return await self._run(*args)

    async def create_dca(
        self,
        amount: str,
        from_token: str,
        to_token: str,
        interval: str = "1d",
    ) -> Dict[str, Any]:
        """Create a Dollar Cost Average (DCA) strategy."""
        return await self._run(
            "automation", "dca", "create",
            "--amount", amount,
            "--from", from_token,
            "--to", to_token,
            "--interval", interval,
        )

    async def create_limit_order(
        self,
        amount: str,
        from_token: str,
        to_token: str,
        target_price: str,
        side: str = "buy",
    ) -> Dict[str, Any]:
        """Create a limit order."""
        return await self._run(
            "automation", "limit", "create",
            "--side", side,
            "--amount", amount,
            "--from", from_token,
            "--to", to_token,
            "--price", target_price,
        )

    # ------------------------------------------------------------------
    # Alerts & Automation
    # ------------------------------------------------------------------

    async def create_price_alert(
        self, token: str, condition: str, value: float
    ) -> Dict[str, Any]:
        """Create a price alert.

        Args:
            token: Token symbol (e.g. "BTC")
            condition: "above" or "below"
            value: Price threshold
        """
        return await self._run(
            "alert", "create",
            "--token", token,
            f"--{condition}", str(value),
        )

    async def list_alerts(self) -> Dict[str, Any]:
        """List all active alerts."""
        return await self._run("alert", "list")

    # ------------------------------------------------------------------
    # x402 Payments
    # ------------------------------------------------------------------

    async def create_x402_endpoint(
        self,
        path: str,
        price: str,
        token: str = "USDC",
    ) -> Dict[str, Any]:
        """Create an x402 pay-per-call endpoint."""
        return await self._run(
            "serve", "x402", "create",
            "--path", path,
            "--price", price,
            "--token", token,
        )

    # ------------------------------------------------------------------
    # Health & Status
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if TWAK CLI is available and authenticated."""
        try:
            result = await self._run("wallet", "info", timeout=10.0)
            return result.get("success", False) and "error" not in result
        except Exception:
            return False

    async def autonomous_trade(
        self,
        signal: Dict[str, Any],
        rules: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an autonomous trade based on a signal.

        This is the main entry point for Track 1 autonomous trading agents.
        Reads CMC signal → decides via TWAK → executes on BSC.

        Args:
            signal: Trading signal dict with keys:
                - action: "buy" | "sell" | "hold"
                - token: Target token symbol
                - amount: Trade amount
                - confidence: 0-1 confidence score
                - reason: Human-readable reason
            rules: Optional risk rules dict:
                - max_position_pct: Max % of portfolio per position
                - max_daily_loss: Max daily loss in USD
                - allowed_tokens: List of allowed token symbols

        Returns:
            Trade execution result
        """
        rules = rules or {}
        action = signal.get("action", "hold")
        token = signal.get("token", "")
        amount = signal.get("amount", "0")
        confidence = signal.get("confidence", 0)

        # Safety: skip low-confidence signals
        min_confidence = rules.get("min_confidence", 0.6)
        if confidence < min_confidence:
            return {
                "success": False,
                "error": f"Confidence {confidence} below minimum {min_confidence}",
                "signal": signal,
            }

        # Safety: only trade allowed tokens
        allowed_tokens = rules.get("allowed_tokens", [])
        if allowed_tokens and token not in allowed_tokens:
            return {
                "success": False,
                "error": f"Token {token} not in allowed list: {allowed_tokens}",
                "signal": signal,
            }

        if action == "hold":
            return {"success": True, "action": "hold", "reason": signal.get("reason", "")}

        if action == "buy":
            stable = rules.get("stablecoin", "USDC")
            return await self.swap(amount, stable, token, quote_only=False)
        elif action == "sell":
            stable = rules.get("stablecoin", "USDC")
            return await self.swap(amount, token, stable, quote_only=False)

        return {"success": False, "error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # Paper mode — simulate trades for Track 2 backtesting
    # ------------------------------------------------------------------

    @dataclass
    class PaperPosition:
        token: str
        amount: float
        entry_price: float
        timestamp: float

    async def paper_swap(
        self,
        amount: str,
        from_token: str,
        to_token: str,
        price: float,
    ) -> Dict[str, Any]:
        """Simulate a swap in paper mode for backtesting."""
        amt = float(amount)
        if from_token.upper() == "USDC":
            # Buy: USDC → TOKEN
            qty = amt / price
            self._paper_balance -= amt
            self._paper_positions[to_token] = TWAKClient.PaperPosition(
                token=to_token, amount=qty, entry_price=price,
                timestamp=asyncio.get_event_loop().time(),
            )
            return {"success": True, "action": "buy", "token": to_token, "amount": qty, "price": price}
        else:
            # Sell: TOKEN → USDC
            pos = self._paper_positions.get(from_token)
            if not pos:
                return {"success": False, "error": f"No position in {from_token}"}
            qty = min(amt, pos.amount)
            proceeds = qty * price
            self._paper_balance += proceeds
            pos.amount -= qty
            if pos.amount <= 0:
                del self._paper_positions[from_token]
            return {"success": True, "action": "sell", "token": from_token, "amount": qty, "proceeds": proceeds}
