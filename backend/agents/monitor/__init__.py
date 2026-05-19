"""
PolyEdge Autonomous Monitor — Self-wake monitoring daemon.

Self-wakes every N minutes to:
1. Check all strategy performance (paper + live)
2. Generate account summary
3. Detect anomalies/degradation
4. Send alerts if thresholds breached
5. Suggest self-improvements
6. Research market opportunities

This is a background daemon that runs autonomously,
separate from the main trading scheduler.
"""

from backend.agents.monitor.monitor_daemon import MonitorDaemon
from backend.agents.monitor.strategy_performance import (
    StrategyPerformanceTracker,
    StrategyReport,
)
from backend.agents.monitor.account_summary import (
    AccountSummary,
    AccountSummarizer,
)
from backend.agents.monitor.alerts import AlertManager
from backend.agents.monitor.research_assistant import (
    ResearchAssistant,
    ResearchSuggestion,
)

__all__ = [
    "MonitorDaemon",
    "StrategyPerformanceTracker",
    "StrategyReport",
    "AccountSummary",
    "AccountSummarizer",
    "AlertManager",
    "ResearchAssistant",
    "ResearchSuggestion",
]
