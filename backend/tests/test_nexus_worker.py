import asyncio

from backend.job_queue.handlers import nexus_signal
from backend.job_queue.worker import Worker


def test_nexus_signal_handler_is_fail_closed():
    result = asyncio.run(nexus_signal({"token_address": "x", "network": "solana"}))
    assert result["success"] is False
    assert result["error_class"] == "permanent"
    assert result["status"] == "NOT_EXECUTED"
    assert result["reason"] in ("EXECUTION_DISABLED", "EXECUTION_HALTED")


def test_worker_dispatches_nexus_signal():
    import inspect

    source = inspect.getsource(Worker.dispatch_job)
    assert '"nexus_signal"' in source
    assert "handlers.nexus_signal(job.payload)" in source
