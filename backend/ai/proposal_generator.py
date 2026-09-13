"""Proposal Generator Module - Wave 4b

Generates strategy improvement proposals using Claude AI based on recent trade analysis.
Proposals are stored in the database with status 'pending_approval' and require admin approval
before execution.

This module integrates with:
- TradeAnalyzer (Wave 4a) for trade pattern analysis
- Claude API for generating improvement recommendations
- Database for proposal persistence
- API endpoints for approval workflow
"""

import json
import re
import statistics as stats_mod
from loguru import logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
from backend.db.utils import get_db_session
from backend.models.database import (
    StrategyConfig,
    StrategyProposal as DBProposal,
    Trade,
)
from backend.ai.trade_analyzer import TradeAnalyzer
from backend.ai.claude import ClaudeAnalyzer
from backend.config import settings
from sqlalchemy.sql import func

from ._proposal_generator_strategyproposal import (
    StrategyProposal,
)

from ._proposal_generator_proposalgenerator import (
    ProposalGenerator,
)

from ._proposal_generator_get_baseline_win_rate import (
    _get_baseline_win_rate,
    _run_backtest_for_proposal,
    auto_promote_eligible_proposals,
)


__all__ = [
    "Any",
    "ClaudeAnalyzer",
    "DBProposal",
    "Dict",
    "List",
    "Optional",
    "ProposalGenerator",
    "StrategyConfig",
    "StrategyProposal",
    "Trade",
    "TradeAnalyzer",
    "_get_baseline_win_rate",
    "_run_backtest_for_proposal",
    "auto_promote_eligible_proposals",
    "dataclass",
    "datetime",
    "func",
    "get_db_session",
    "json",
    "logger",
    "re",
    "settings",
    "stats_mod",
    "timezone",
]
