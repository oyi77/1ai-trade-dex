"""Activity tracking module — imports tracker singleton."""

from backend.core.activity.tracker import ActivityTracker

# Module-level tracker singleton — initialized by orchestrator
tracker = None


def get_tracker() -> ActivityTracker:
    """Get the module-level tracker instance."""
    if tracker is None:
        raise RuntimeError("ActivityTracker not initialized. Start orchestrator first.")
    return tracker


def set_tracker(t: ActivityTracker):
    global tracker
    tracker = t