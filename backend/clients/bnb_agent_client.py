"""BNB AI Agent SDK client for BNB HACK hackathon.

Wraps the bnbagent Python SDK for:
- ERC-8004: Agent identity registration on BSC
- ERC-8183: Agentic commerce protocol (jobs, escrow, settlement)
- Wallet management: EVM key handling via EVMWalletProvider
- BSC testnet faucet and contract interaction

Install: pip install bnbagent

For the hackathon:
  Track 1 — Register agent identity, receive on-chain jobs
  Track 2 — Not directly applicable (strategy skills don't need on-chain)

Key contracts on BSC Testnet (Chain ID 97):
  Identity Registry (ERC-8004): 0x8004A818BFB912233c491871b3d84c89A494BD9e
  AgenticCommerce (ERC-8183): 0xa206c0517b6371c6638cd9e4a42cc9f02a33b0de
  EvaluatorRouter:            0xd7d36d66d2f1b608a0f943f722d27e3744f66f25
  OptimisticPolicy:           0x4f4678d4439fec812ac7674bb3efb4c8f5fb78a6

BSC Mainnet (Chain ID 56):
  Identity Registry (ERC-8004): 0x8004A169FB4a3325136EB29fA0ceB6D2e539a432
  AgenticCommerce (ERC-8183): 0xea4daa3100a767e86fded867729ae7446476eba6
  EvaluatorRouter:            0x51895229e12f9876011789b04f8698af06ccd6da
  OptimisticPolicy:           0x9c01845705b3078aa2e8cff7520a6376fd766de5
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

_BNBAGENT_AVAILABLE = False
try:
    from bnbagent import ERC8004Agent, AgentEndpoint, EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    _BNBAGENT_AVAILABLE = True
except ImportError:
    logger.warning(
        "bnbagent SDK not installed. Install with: pip install bnbagent"
    )


@dataclass
class BNBAgentConfig:
    """BNB Agent SDK configuration."""
    network: str = field(
        default_factory=lambda: os.getenv("BNB_NETWORK", "bsc-testnet")
    )
    wallet_password: str = field(
        default_factory=lambda: os.getenv("WALLET_PASSWORD", "")
    )
    private_key: Optional[str] = field(
        default_factory=lambda: os.getenv("PRIVATE_KEY")
    )
    wallet_address: Optional[str] = field(
        default_factory=lambda: os.getenv("WALLET_ADDRESS")
    )
    rpc_url: Optional[str] = field(
        default_factory=lambda: os.getenv("BNB_RPC_URL")
    )
    erc8183_agent_url: Optional[str] = field(
        default_factory=lambda: os.getenv("ERC8183_AGENT_URL")
    )
    erc8183_service_price: str = field(
        default_factory=lambda: os.getenv(
            "ERC8183_SERVICE_PRICE", "1000000000000000000"
        )
    )


class BNBAgentClient:
    """Python client for BNB AI Agent SDK.

    Provides agent identity registration (ERC-8004) and agentic commerce (ERC-8183)
    capabilities for the hackathon Track 1 autonomous trading agent.

    Usage:
        client = BNBAgentClient(BNBAgentConfig())
        agent_id = await client.register_agent(
            name="PolyEdge Trading Agent",
            description="AI-powered autonomous trading agent on BSC",
        )
    """

    def __init__(self, config: Optional[BNBAgentConfig] = None):
        if not _BNBAGENT_AVAILABLE:
            raise ImportError(
                "bnbagent SDK required. Install: pip install bnbagent"
            )
        self.config = config or BNBAgentConfig()
        self._wallet: Optional[Any] = None
        self._erc8004: Optional[Any] = None
        self._erc8183: Optional[Any] = None
        self._initialized = False

    async def initialize(self) -> Dict[str, Any]:
        """Initialize wallet and SDK clients."""
        if self._initialized:
            return {"status": "already_initialized"}

        try:
            self._wallet = EVMWalletProvider(
                password=self.config.wallet_password,
                private_key=self.config.private_key,
            )
            self._erc8004 = ERC8004Agent(
                network=self.config.network,
                wallet_provider=self._wallet,
            )
            self._erc8183 = ERC8183Client(
                self._wallet,
                network=self.config.network,
            )
            self._initialized = True
            return {
                "status": "initialized",
                "address": self._wallet.address(),
                "network": self.config.network,
            }
        except Exception as e:
            logger.error(f"BNB Agent SDK init failed: {e}")
            return {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    # ERC-8004: Agent Identity
    # ------------------------------------------------------------------

    async def register_agent(
        self,
        name: str,
        description: str,
        endpoints: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Register this agent on-chain with ERC-8004 identity.

        Gas-free on BSC Testnet via MegaFuel paymaster sponsorship.

        Args:
            name: Agent display name
            description: Agent capability description
            endpoints: List of {"name": str, "endpoint": str, "version": str}
        """
        if not self._initialized:
            await self.initialize()

        agent_endpoints = []
        if endpoints:
            agent_endpoints = [
                AgentEndpoint(
                    name=ep["name"],
                    endpoint=ep["endpoint"],
                    version=ep.get("version", "0.1.0"),
                )
                for ep in endpoints
            ]

        agent_uri = self._erc8004.generate_agent_uri(
            name=name,
            description=description,
            endpoints=agent_endpoints,
        )

        result = self._erc8004.register_agent(agent_uri=agent_uri)
        return {
            "agent_id": result.get("agentId"),
            "transaction_hash": result.get("transactionHash"),
            "name": name,
            "network": self.config.network,
        }

    async def get_agent_info(self) -> Dict[str, Any]:
        """Get registered agent information."""
        if not self._initialized:
            await self.initialize()
        return {
            "address": self._wallet.address(),
            "network": self.config.network,
            "testnet": self.config.network == "bsc-testnet",
        }

    # ------------------------------------------------------------------
    # ERC-8183: Agentic Commerce
    # ------------------------------------------------------------------

    async def create_job(
        self,
        provider: str,
        description: str,
        budget: Optional[int] = None,
        expired_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create an ERC-8183 job for another agent."""
        import time

        if not self._initialized:
            await self.initialize()

        if budget is None:
            decimals = self._erc8183.token_decimals()
            budget = 1 * (10 ** decimals)

        if expired_at is None:
            expired_at = int(time.time()) + 3600  # 1 hour

        result = self._erc8183.create_job(
            provider=provider,
            expired_at=expired_at,
            description=description,
        )
        job_id = result.get("jobId")
        self._erc8183.register_job(job_id)
        self._erc8183.set_budget(job_id, budget)
        self._erc8183.fund(job_id, budget)

        return {
            "job_id": job_id,
            "provider": provider,
            "budget": budget,
            "expired_at": expired_at,
            "status": "FUNDED",
        }

    async def get_job_status(self, job_id: int) -> Dict[str, Any]:
        """Get ERC-8183 job status."""
        if not self._initialized:
            await self.initialize()

        status = self._erc8183.get_job_status(job_id)
        return {
            "job_id": job_id,
            "status": status.name if hasattr(status, "name") else str(status),
        }

    async def settle_job(self, job_id: int) -> Dict[str, Any]:
        """Permissionless settlement of a completed job."""
        if not self._initialized:
            await self.initialize()

        self._erc8183.settle(job_id)
        return {"job_id": job_id, "settled": True}

    # ------------------------------------------------------------------
    # Wallet helpers
    # ------------------------------------------------------------------

    async def get_balance(self) -> Dict[str, Any]:
        """Get agent wallet balance."""
        if not self._initialized:
            await self.initialize()

        symbol = self._erc8183.token_symbol()
        decimals = self._erc8183.token_decimals()
        balance_raw = self._erc8183.token_balance()
        balance = balance_raw / (10 ** decimals)

        return {
            "address": self._wallet.address(),
            "symbol": symbol,
            "decimals": decimals,
            "balance": balance,
            "balance_raw": balance_raw,
            "network": self.config.network,
        }

    async def health_check(self) -> bool:
        """Verify BNB Agent SDK is operational."""
        if not _BNBAGENT_AVAILABLE:
            return False
        try:
            if not self._initialized:
                result = await self.initialize()
                return result.get("status") == "initialized"
            balance = await self.get_balance()
            return "address" in balance
        except Exception as e:
            logger.debug(f"BNB Agent health check failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Hackathon-specific: Agent trading identity
    # ------------------------------------------------------------------

    async def register_trading_agent(
        self,
        strategy_name: str = "PolyEdge Autonomous Trader",
    ) -> Dict[str, Any]:
        """Register as a trading agent for the BNB HACK hackathon.

        Sets up ERC-8004 identity with trading-specific endpoints.
        Call this once before the live trading window (June 22-28).

        Returns agent identity info for submission.
        """
        endpoints = [
            {
                "name": "ERC-8183 Trading Endpoint",
                "endpoint": f"{self.config.erc8183_agent_url or 'http://localhost:8100'}/erc8183/status",
                "version": "0.1.0",
            },
            {
                "name": "CMC Signal Ingestion",
                "endpoint": f"{self.config.erc8183_agent_url or 'http://localhost:8100'}/api/v1/agent/signals",
                "version": "0.1.0",
            },
        ]

        return await self.register_agent(
            name=strategy_name,
            description=(
                "Autonomous AI trading agent powered by PolyEdge. "
                "Reads CMC market signals, analyzes via AGI debate engine, "
                "executes trades on BSC via TWAK. "
                "14 strategies, Kelly sizing, drawdown protection."
            ),
            endpoints=endpoints,
        )
