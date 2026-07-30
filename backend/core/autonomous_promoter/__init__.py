"""AutonomousPromoter — Strategy promotion and demotion engine.

Package split from backend/core/autonomous_promoter.py.
"""

from .criteria import CriteriaMixin
from .workflow import WorkflowMixin
from .review import ReviewMixin


class AutonomousPromoter(CriteriaMixin, WorkflowMixin, ReviewMixin):
    """Strategy promotion and demotion engine."""
    pass


from .job import autonomous_promotion_job, autonomous_promoter  # noqa: E402 — must come after class def

__all__ = ["AutonomousPromoter", "autonomous_promotion_job", "autonomous_promoter"]
