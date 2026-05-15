from abc import ABC, abstractmethod

class AGIScoreMetric(ABC):
    """Base class for AGI-aligned scoring metrics."""
    
    @abstractmethod
    def score(self, result: any) -> float:
        """Compute raw score for a given result."""
        pass

    @abstractmethod
    def thresholds(self) -> dict[str, float]:
        """Return performance thresholds (e.g., 'fail', 'pass', 'excellent')."""
        pass

    def normalize(self, score: float) -> float:
        """Normalize score to 0.0-1.0 range."""
        return max(0.0, min(1.0, score))
