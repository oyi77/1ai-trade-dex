"""EvolutionAction dataclass for tracking evolution events.

Wave 10: Evolution Scheduler — Part 9
Tracks all evolution actions (mutation, crossover, selection, fitness_eval, etc.)
and publishes them as events.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any


@dataclass
class EvolutionAction:
    """Represents an evolution event in the system."""
    
    action_type: str  # "mutation", "crossover", "selection", "fitness_eval", "promotion", "auto_kill", "necromancy"
    genome_id: str
    strategy_name: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    from_stage: Optional[str] = None
    to_stage: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert EvolutionAction to dictionary for event publishing."""
        return {
            "action_type": self.action_type,
            "genome_id": self.genome_id,
            "strategy_name": self.strategy_name,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
        }
