"""Auto-retraining trigger — fires after sufficient settled trades or Brier degradation."""
import asyncio
import logging
import threading
from backend.models.database import SessionLocal, Trade

logger = logging.getLogger("trading_bot.retrain")

# Module-level accuracy tracker (thread-safe via lock)
_best_accuracy = 0.0
_accuracy_lock = threading.Lock()


def get_best_accuracy() -> float:
    with _accuracy_lock:
        return _best_accuracy


def set_best_accuracy(value: float) -> None:
    global _best_accuracy
    with _accuracy_lock:
        _best_accuracy = value


async def check_and_trigger_retraining() -> dict:
    try:
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            settled_count = db.query(Trade).filter(Trade.settled == True).count()
            if settled_count < 50:
                return {"status": "skipped", "reason": f"only {settled_count} settled trades, need 50"}
            from backend.ai.training.train import run_training_pipeline
            result = await run_training_pipeline(min_examples=200)
            if result["status"] == "ok":
                try:
                    old_accuracy = get_best_accuracy()
                    new_accuracy = result["accuracy"]
                    if new_accuracy >= old_accuracy:
                        set_best_accuracy(new_accuracy)
                        logger.info(f"Retraining accepted: acc={new_accuracy:.3f} >= {old_accuracy:.3f}")
                    else:
                        logger.warning(f"Retraining rejected: acc={new_accuracy:.3f} < {old_accuracy:.3f}")
                        result["status"] = "degraded"
                except Exception as e:
                    logger.error(f"Accuracy comparison failed: {e}")
            return result
    except Exception as e:
        logger.error(f"Retrain trigger failed: {e}")
        return {"status": "error", "reason": str(e)}
