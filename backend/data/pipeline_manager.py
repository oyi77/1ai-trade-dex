"""Data pipeline manager — orchestrates all data source refreshes.

Coordinates HF dataset refresh, Dune queries, subgraph sync, and Hyperliquid
market data into a unified pipeline with scheduling, freshness monitoring,
and health reporting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from loguru import logger


class PipelineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass
class PipelineStageResult:
    """Result of a single pipeline stage execution."""

    name: str
    status: PipelineStatus
    records_processed: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    last_run: float = 0.0


@dataclass
class PipelineHealth:
    """Overall pipeline health report."""

    stages: dict[str, PipelineStageResult]
    total_records: int = 0
    stale_stages: list[str] = field(default_factory=list)
    overall_status: PipelineStatus = PipelineStatus.IDLE


@dataclass
class DataPipelineManager:
    """Orchestrates data source refreshes across all pipelines.

    Manages scheduling (daily refresh, weekly full sync) and monitors
    data freshness across all connected data sources.

    Stages:
    - dune: Dune Analytics queries (volume, whale activity)
    - subgraph: Polymarket subgraph sync (markets, trades, settlements)
    - hyperliquid: Hyperliquid market data refresh
    - hf_dataset: HuggingFace dataset refresh (if configured)
    """

    _stages: dict[str, PipelineStageResult] = field(default_factory=dict)
    _running: bool = False
    _dune_client: Any = None
    _subgraph_client: Any = None
    _hl_client: Any = None
    _freshness_threshold_seconds: float = 7200.0  # 2 hours

    def __post_init__(self):
        self._stages = {
            "dune": PipelineStageResult(name="dune", status=PipelineStatus.IDLE),
            "subgraph": PipelineStageResult(
                name="subgraph", status=PipelineStatus.IDLE
            ),
            "hyperliquid": PipelineStageResult(
                name="hyperliquid", status=PipelineStatus.IDLE
            ),
            "hf_dataset": PipelineStageResult(
                name="hf_dataset", status=PipelineStatus.IDLE
            ),
        }

    def register_dune_client(self, client: Any) -> None:
        """Register the Dune Analytics client."""
        self._dune_client = client
        logger.info("[pipeline] Registered Dune Analytics client")

    def register_subgraph_client(self, client: Any) -> None:
        """Register the Polymarket subgraph client."""
        self._subgraph_client = client
        logger.info("[pipeline] Registered Polymarket subgraph client")

    def register_hyperliquid_client(self, client: Any) -> None:
        """Register the Hyperliquid client."""
        self._hl_client = client
        logger.info("[pipeline] Registered Hyperliquid client")

    async def run_stage(self, stage_name: str) -> PipelineStageResult:
        """Run a single pipeline stage.

        Args:
            stage_name: One of 'dune', 'subgraph', 'hyperliquid', 'hf_dataset'.

        Returns:
            PipelineStageResult with status and metrics.
        """
        if stage_name not in self._stages:
            return PipelineStageResult(
                name=stage_name,
                status=PipelineStatus.FAILED,
                error=f"Unknown stage: {stage_name}",
            )

        stage = self._stages[stage_name]
        stage.status = PipelineStatus.RUNNING
        start = time.monotonic()

        try:
            records = 0

            if stage_name == "dune":
                records = await self._run_dune_stage()
            elif stage_name == "subgraph":
                records = await self._run_subgraph_stage()
            elif stage_name == "hyperliquid":
                records = await self._run_hyperliquid_stage()
            elif stage_name == "hf_dataset":
                records = await self._run_hf_dataset_stage()

            stage.records_processed = records
            stage.status = PipelineStatus.COMPLETED
            stage.error = None
            logger.info(
                "[pipeline] Stage '%s' completed: %d records", stage_name, records
            )

        except Exception as e:
            stage.status = PipelineStatus.FAILED
            stage.error = str(e)
            logger.error("[pipeline] Stage '%s' failed: %s", stage_name, e)

        finally:
            stage.duration_seconds = time.monotonic() - start
            stage.last_run = time.time()

        return stage

    async def _run_dune_stage(self) -> int:
        """Execute Dune Analytics queries."""
        if self._dune_client is None:
            logger.debug("[pipeline] Dune client not registered, skipping")
            return 0

        total = 0
        # Fetch whale activity (most useful for trading)
        whales = await self._dune_client.get_whale_activity()
        total += len(whales)
        logger.debug("[pipeline] Dune whale activity: %d records", len(whales))

        # Fetch top markets
        markets = await self._dune_client.get_top_markets()
        total += len(markets)
        logger.debug("[pipeline] Dune top markets: %d records", len(markets))

        # Fetch settlement history (historical, cached for 24h)
        settlements = await self._dune_client.get_settlement_history()
        total += len(settlements)
        logger.debug("[pipeline] Dune settlements: %d records", len(settlements))

        return total

    async def _run_subgraph_stage(self) -> int:
        """Execute Polymarket subgraph sync."""
        if self._subgraph_client is None:
            logger.debug("[pipeline] Subgraph client not registered, skipping")
            return 0

        total = 0
        # Sync market data
        markets = await self._subgraph_client.get_markets(first=500)
        total += len(markets)
        logger.debug("[pipeline] Subgraph markets: %d records", len(markets))

        # Sync recent trades
        trades = await self._subgraph_client.get_trades(first=1000)
        total += len(trades)
        logger.debug("[pipeline] Subgraph trades: %d records", len(trades))

        # Sync settlements
        settlements = await self._subgraph_client.get_settlements(first=200)
        total += len(settlements)
        logger.debug("[pipeline] Subgraph settlements: %d records", len(settlements))

        return total

    async def _run_hyperliquid_stage(self) -> int:
        """Refresh Hyperliquid market data."""
        if self._hl_client is None:
            logger.debug("[pipeline] Hyperliquid client not registered, skipping")
            return 0

        total = 0
        markets = await self._hl_client.get_markets()
        total += len(markets)
        logger.debug("[pipeline] Hyperliquid markets: %d records", len(markets))

        return total

    async def _run_hf_dataset_stage(self) -> int:
        """Refresh HuggingFace datasets (if configured).

        This stage checks for a configured HF dataset token and refreshes
        trading history data. Skipped if not configured.
        """
        try:
            hf_token = getattr(
                __import__("backend.config", fromlist=["settings"]).settings,
                "HF_DATASET_TOKEN",
                "",
            )
            if not hf_token:
                logger.debug("[pipeline] HF dataset not configured, skipping")
                return 0

            # HF dataset refresh logic would go here
            # For now, report 0 records as placeholder
            logger.info("[pipeline] HF dataset refresh completed (placeholder)")
            return 0
        except Exception as e:
            logger.warning("[pipeline] HF dataset stage error: %s", e)
            return 0

    async def run_daily_refresh(self) -> PipelineHealth:
        """Run the daily data refresh pipeline.

        Executes: dune, subgraph, hyperliquid stages.
        Skips: hf_dataset (weekly only).
        """
        logger.info("[pipeline] Starting daily refresh")
        self._running = True

        try:
            for stage_name in ("dune", "subgraph", "hyperliquid"):
                await self.run_stage(stage_name)
        finally:
            self._running = False

        return self.get_health()

    async def run_weekly_full_sync(self) -> PipelineHealth:
        """Run a full weekly sync across all data sources.

        Executes all stages including hf_dataset.
        """
        logger.info("[pipeline] Starting weekly full sync")
        self._running = True

        try:
            for stage_name in self._stages:
                await self.run_stage(stage_name)
        finally:
            self._running = False

        return self.get_health()

    def get_health(self) -> PipelineHealth:
        """Get current pipeline health report.

        Returns:
            PipelineHealth with stage results, staleness info, and overall status.
        """
        stale = []
        now = time.time()

        for name, stage in self._stages.items():
            if (
                stage.last_run > 0
                and (now - stage.last_run) > self._freshness_threshold_seconds
            ):
                stale.append(name)

        overall = PipelineStatus.COMPLETED
        for stage in self._stages.values():
            if stage.status == PipelineStatus.FAILED:
                overall = PipelineStatus.FAILED
                break
            elif stage.status == PipelineStatus.RUNNING:
                overall = PipelineStatus.RUNNING
            elif (
                stage.status == PipelineStatus.IDLE and overall != PipelineStatus.FAILED
            ):
                overall = PipelineStatus.IDLE

        return PipelineHealth(
            stages=dict(self._stages),
            total_records=sum(s.records_processed for s in self._stages.values()),
            stale_stages=stale,
            overall_status=overall,
        )

    def is_running(self) -> bool:
        """Check if a pipeline is currently executing."""
        return self._running


# Module-level singleton
pipeline_manager = DataPipelineManager()
