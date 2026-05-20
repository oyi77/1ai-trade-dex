"""
MonitorDaemon — Self-wake autonomous monitoring engine.

Architecture:
    ┌──────────────────────────────┐
    │      MonitorDaemon           │  ← self-wakes every N seconds
    │  ┌────────────────────────┐  │
    │  │ Poll Loop (async)      │  │
    │  │  every MONITOR_INTERVAL│  │
    │  └────────┬───────────────┘  │
    │           ▼                  │
    │  ┌────────────────────────┐  │
    │  │ StrategyPerformance    │  │  ← paper + live PnL, WR, drawdown
    │  ├────────────────────────┤  │
    │  │ AccountSummary         │  │  ← balances, open positions, equity
    │  ├────────────────────────┤  │
    │  │ AnomalyDetector        │  │  ← degradation, stale strategies
    │  ├────────────────────────┤  │
    │  │ AlertManager           │  │  ← Telegram + console alerts
    │  ├────────────────────────┤  │
    │  │ ResearchAssistant      │  │  ← opportunity suggestions
    │  └────────────────────────┘  │
    └──────────────────────────────┘

Self-Wake mechanics:
- Runs in its own asyncio event loop (separate thread)
- Interval-based polling (configurable via MONITOR_INTERVAL)
- No cron/systemd dependency — purely self-contained
- Graceful shutdown on SIGTERM/SIGINT
- Stale detection: if no heartbeat from strategies in >15min → alert
"""

import asyncio
import json
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

from loguru import logger

from backend.config import settings
from backend.agents.monitor.strategy_performance import (
    StrategyPerformanceTracker,
    StrategyReport,
)
from backend.agents.monitor.account_summary import AccountSummarizer
from backend.agents.monitor.alerts import AlertManager
from backend.agents.monitor.research_assistant import ResearchAssistant

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MONITOR_INTERVAL = 900  # 15 minutes between self-wake cycles
REPORT_INTERVAL = 3600  # Full report every hour
CRITICAL_CHECK_INTERVAL = 60  # Critical checks every minute
HEARTBEAT_STALE_MINUTES = 15  # Alert if strategy heartbeat older than this
MAX_CONSECUTIVE_FAILURES = 3  # Auto-disable if this many failures
STATE_FILE = Path(settings.DB_BACKUP_DIR or ".") / "monitor_state.json"

# ---------------------------------------------------------------------------
# Monitor Daemon
# ---------------------------------------------------------------------------


class MonitorDaemon:
    """
    Self-wake autonomous monitoring daemon for PolyEdge.

    Starts its own polling loop in a background thread. Reports to Telegram
    and console. Generates periodic summaries and anomaly alerts.

    Usage:
        daemon = MonitorDaemon()
        daemon.start()              # Background thread → runs forever
        await daemon.run_once()     # Single cycle (for scheduler integration)
        daemon.stop()               # Graceful shutdown
    """

    def __init__(
        self,
        monitor_interval: int = DEFAULT_MONITOR_INTERVAL,
        report_interval: int = REPORT_INTERVAL,
        alert_on_startup: bool = True,
    ):
        self.monitor_interval = monitor_interval
        self.report_interval = report_interval
        self.alert_on_startup = alert_on_startup

        # Sub-modules
        self.strategy_tracker = StrategyPerformanceTracker()
        self.account_summarizer = AccountSummarizer()
        self.alert_manager = AlertManager()
        self.research_assistant = ResearchAssistant()

        # State
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_report_time: float = 0.0
        self._cycle_count: int = 0
        self._consecutive_failures: int = 0
        self._last_heartbeat_ts: Dict[str, float] = {}

        # Signal handling
        self._shutdown_event = threading.Event()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Start the monitoring daemon in a background thread."""
        if self._running:
            logger.warning("[MonitorDaemon] Already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="polyedge-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"[MonitorDaemon] Started (interval={self.monitor_interval}s, "
            f"report_interval={self.report_interval}s)"
        )

    def stop(self) -> None:
        """Graceful shutdown of the monitoring daemon."""
        self._running = False
        self._shutdown_event.set()
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("[MonitorDaemon] Stopped")

    async def run_once(self) -> dict:
        """
        Run a single monitor cycle (for scheduler/AGI integration).

        Returns: full report dict {
            'status': 'healthy' | 'warning' | 'critical',
            'strategies': {...},
            'accounts': {...},
            'alerts': [...],
            'research': {...},
            'timestamp': iso_string,
        }
        """
        self._cycle_count += 1
        cycle_start = time.time()
        report: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle": self._cycle_count,
            "status": "healthy",
            "strategies": {},
            "accounts": {},
            "alerts": [],
            "research": {},
            "warnings": [],
            "critical": [],
        }

        try:
            # ── Phase 1: Strategy Performance ──
            strategy_reports = await self.strategy_tracker.fetch_all()
            report["strategies"] = {
                name: sr.to_dict() for name, sr in strategy_reports.items()
            }

            # Check for stale strategies
            for name, sr in strategy_reports.items():
                if sr.is_stale:
                    report["warnings"].append(
                        f"Strategy '{name}' stale — no heartbeat in "
                        f"{sr.hours_since_heartbeat:.1f}h"
                    )
                    self._last_heartbeat_ts[name] = time.time()
                    await self.alert_manager.send_alert(
                        title=f"⚠️ Stale Strategy: {name}",
                        body=(
                            f"Last heartbeat: {sr.hours_since_heartbeat:.1f}h ago\n"
                            f"Status: {sr.status}\n"
                            f"Mode: {sr.mode}"
                        ),
                        level="warning",
                    )

            # ── Phase 2: Account Summary ──
            accounts = await self.account_summarizer.summarize_all()
            report["accounts"] = accounts

            # Check for critical account issues
            for mode, summary in accounts.items():
                if summary.get("status") == "error":
                    report["critical"].append(
                        f"Account '{mode}' errored: {summary.get('error')}"
                    )
                elif summary.get("pnl_daily", 0) < -settings.RISK_DAILY_LOSS_LIMIT:
                    report["critical"].append(
                        f"Account '{mode}' daily loss ${summary['pnl_daily']:.2f} "
                        f"exceeds limit ${settings.RISK_DAILY_LOSS_LIMIT}"
                    )

            # ── Phase 3: Anomaly Detection ──
            anomalies = await self._detect_anomalies(strategy_reports)
            report["alerts"].extend(anomalies)

            # ── Phase 4: Research Suggestions ──
            if self._should_run_research():
                research = await self.research_assistant.generate_suggestions(
                    account_summary=accounts,
                    strategy_reports=list(strategy_reports.values()),
                )
                report["research"] = research.to_dict() if research else {}
            else:
                report["research"] = {"skipped": True}

            # ── Phase 5: Report Generation ──
            now = time.time()
            if (now - self._last_report_time) >= self.report_interval:
                await self._send_full_report(report)
                self._last_report_time = now
            elif report["critical"] or report["warnings"]:
                await self._send_quick_alert(report)

            # ── Status Determination ──
            if report["critical"]:
                report["status"] = "critical"
            elif report["warnings"]:
                report["status"] = "warning"
            else:
                report["status"] = "healthy"

            # Reset failure counter on success
            self._consecutive_failures = 0

        except Exception as exc:
            self._consecutive_failures += 1
            logger.opt(exception=True).error(
                f"[MonitorDaemon] Cycle {self._cycle_count} failed: {exc}"
            )
            report["status"] = "error"
            report["errors"] = [str(exc)]

            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                await self.alert_manager.send_alert(
                    title="🚨 Monitor Daemon Failure",
                    body=(
                        f"{self._consecutive_failures} consecutive failures.\n"
                        f"Last error: {exc}\n"
                        f"Auto-disabling monitor."
                    ),
                    level="critical",
                )
                self.stop()

        # Save state
        self._save_state(report)

        elapsed = time.time() - cycle_start
        logger.info(
            f"[MonitorDaemon] Cycle {self._cycle_count} complete "
            f"({elapsed:.1f}s) status={report['status']}"
        )

        return report

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    def _run_event_loop(self) -> None:
        """Background thread entry point. Runs the async polling loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Register signal handlers for graceful shutdown
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                self._loop.add_signal_handler(sig, self.stop)
        except (ValueError, NotImplementedError):
            pass  # Windows or non-main thread

        try:
            self._loop.run_until_complete(self._poll_loop())
        except asyncio.CancelledError:
            pass
        finally:
            self._loop.close()
            logger.info("[MonitorDaemon] Event loop closed")

    async def _poll_loop(self) -> None:
        """Main polling loop — self-wakes at monitor_interval."""
        # Send startup alert
        if self.alert_on_startup:
            await self.alert_manager.send_alert(
                title="🔍 PolyEdge Monitor Started",
                body=(
                    f"Interval: {self.monitor_interval}s\n"
                    f"Report interval: {self.report_interval}s\n"
                    f"Modes: {settings.active_modes_set}\n"
                    f"Max daily loss: ${settings.RISK_DAILY_LOSS_LIMIT}"
                ),
                level="info",
            )

        while self._running and not self._shutdown_event.is_set():
            try:
                await self.run_once()
            except Exception as exc:
                logger.opt(exception=True).error(
                    f"[MonitorDaemon] Poll cycle error: {exc}"
                )

            # Wait for next interval (or shutdown signal)
            await self._sleep_or_shutdown(self.monitor_interval)

        logger.info("[MonitorDaemon] Poll loop exited")

    async def _sleep_or_shutdown(self, seconds: float) -> None:
        """Sleep for `seconds` but wake up early if shutdown requested."""
        step = 1.0
        elapsed = 0.0
        while elapsed < seconds and self._running and not self._shutdown_event.is_set():
            await asyncio.sleep(min(step, seconds - elapsed))
            elapsed += step

    async def _detect_anomalies(
        self, strategy_reports: Dict[str, StrategyReport]
    ) -> List[dict]:
        """Detect anomalies across strategies."""
        anomalies = []

        for name, sr in strategy_reports.items():
            # Degradation: WR dropped significantly
            if sr.recent_win_rate is not None and sr.historical_win_rate is not None:
                wr_drop = sr.historical_win_rate - sr.recent_win_rate
                if wr_drop > 0.20:  # 20% WR drop
                    anomalies.append(
                        {
                            "type": "degradation",
                            "strategy": name,
                            "detail": (
                                f"WR dropped {wr_drop:.1%} "
                                f"({sr.historical_win_rate:.1%}→{sr.recent_win_rate:.1%})"
                            ),
                            "level": "warning",
                        }
                    )

            # Consecutive losses
            if sr.consecutive_losses >= 3:
                anomalies.append(
                    {
                        "type": "consecutive_losses",
                        "strategy": name,
                        "detail": f"{sr.consecutive_losses} consecutive losses",
                        "level": "warning" if sr.consecutive_losses < 5 else "critical",
                    }
                )

            # Profit factor below 1.0 (not profitable)
            if (
                sr.profit_factor is not None
                and sr.profit_factor < 0.8
                and sr.total_trades >= 10
            ):
                anomalies.append(
                    {
                        "type": "unprofitable",
                        "strategy": name,
                        "detail": (
                            f"Profit factor {sr.profit_factor:.2f} "
                            f"(below 0.8 threshold)"
                        ),
                        "level": "warning",
                    }
                )

        return anomalies

    def _should_run_research(self) -> bool:
        """Run research every 4 hours or first cycle."""
        if self._cycle_count <= 2:
            return True
        return self._cycle_count % max(1, int(14400 / self.monitor_interval)) == 0

    async def _send_full_report(self, report: dict) -> None:
        """Send comprehensive report via alerts."""
        lines = [
            "📊 POLYEDGE MONITOR REPORT",
            f"Cycle #{report['cycle']} | {report['timestamp'][:19]}",
            f"Status: {report['status'].upper()}",
            "",
        ]

        # Account summaries
        for mode, acct in report.get("accounts", {}).items():
            lines.extend(
                [
                    f"┌─ {mode.upper()} ACCOUNT ──┐",
                    f"  Balance: ${acct.get('balance', 0):.2f}",
                    f"  Open Positions: {acct.get('open_positions', 0)}",
                    f"  Daily PnL: ${acct.get('pnl_daily', 0):+.2f}",
                    f"  Total PnL: ${acct.get('pnl_total', 0):+.2f}",
                    f"  Win Rate: {acct.get('win_rate', 0):.1%}",
                    "",
                ]
            )

        # Strategy health
        for name, sr in report.get("strategies", {}).items():
            status_emoji = (
                "🟢"
                if sr.get("status") == "healthy"
                else "🟡" if sr.get("status") == "warning" else "🔴"
            )
            lines.append(
                f"{status_emoji} {name}: {sr.get('total_trades', 0)} trades | "
                f"PnL ${sr.get('pnl', 0):+.2f} | "
                f"WR {sr.get('win_rate', 0):.1%} | "
                f"PF {sr.get('profit_factor', 0):.2f}"
            )

        # Warnings & Critical
        if report.get("warnings"):
            lines.extend(["", "⚠️ WARNINGS:"] + [f"  • {w}" for w in report["warnings"]])
        if report.get("critical"):
            lines.extend(
                ["", "🚨 CRITICAL:"] + [f"  • {c}" for c in report["critical"]]
            )
        if report.get("research", {}).get("suggestions"):
            lines.extend(
                ["", "💡 RESEARCH SUGGESTIONS:"]
                + [f"  • {s}" for s in report["research"]["suggestions"][:3]]
            )

        await self.alert_manager.send_alert(
            title="📊 PolyEdge Monitor Report",
            body="\n".join(lines),
            level="info" if report["status"] == "healthy" else "warning",
        )

    async def _send_quick_alert(self, report: dict) -> None:
        """Send a quick alert for warnings/critical only (not full report)."""
        items = []
        for w in report.get("warnings", []):
            items.append(f"⚠️ {w}")
        for c in report.get("critical", []):
            items.append(f"🚨 {c}")

        if items:
            await self.alert_manager.send_alert(
                title="🔔 PolyEdge Alert",
                body="\n".join(items),
                level="critical" if report["critical"] else "warning",
            )

    def _save_state(self, report: dict) -> None:
        """Persist monitor state for crash recovery."""
        try:
            state = {
                "last_cycle": report["cycle"],
                "last_timestamp": report["timestamp"],
                "last_status": report["status"],
                "last_accounts": {
                    k: {
                        "balance": v.get("balance", 0),
                        "pnl_total": v.get("pnl_total", 0),
                        "open_positions": v.get("open_positions", 0),
                    }
                    for k, v in report.get("accounts", {}).items()
                },
                "consecutive_failures": self._consecutive_failures,
            }
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception as exc:
            logger.debug(f"[MonitorDaemon] Failed to save state: {exc}")

    @staticmethod
    def load_last_state() -> Optional[dict]:
        """Load last saved state (for recovery/startup comparison)."""
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text())
        except Exception:
            logger.exception("Failed to load monitor daemon state from %s", STATE_FILE)
        return None

    @property
    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())
