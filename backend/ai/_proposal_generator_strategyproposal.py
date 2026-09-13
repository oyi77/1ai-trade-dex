"""Carved verbatim out of ``backend/ai/proposal_generator.py`` — statements moved, no logic changed."""

from .proposal_generator import (
    dataclass,
)

from . import proposal_generator as _facade

@dataclass
class StrategyProposal:
    """Strategy improvement proposal data structure."""

    strategy_name: str
    change_type: str  # "parameter_adjustment", "threshold_change", "new_feature"
    change_details: _facade.Dict[str, _facade.Any]
    expected_impact: str
    reasoning: str
    confidence: float  # 0.0-1.0
    priority: str  # "high", "medium", "low"
    estimated_improvement: _facade.Optional[float] = (
        None  # Expected % improvement in win rate or PnL
    )
