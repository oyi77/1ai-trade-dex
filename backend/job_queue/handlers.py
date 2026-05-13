"""Job handlers for queue execution.

Each handler returns structured results with error classification:
- transient: network/timeout errors that should retry
- permanent: invalid data that should fail immediately
"""

from typing import Dict, Any

from loguru import logger

_TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError)


def _classify_error(e: Exception) -> str:
    if isinstance(e, _TRANSIENT_ERRORS):
        return "transient"
    if "timeout" in str(e).lower() or "connection" in str(e).lower():
        return "transient"
    if "rate limit" in str(e).lower() or "429" in str(e):
        return "transient"
    return "permanent"


async def market_scan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for market scanning job.

    Wraps the existing scan_and_trade_job logic from scheduler.py.
    Can be called from async worker context.

    Args:
        payload: Dict containing optional job parameters

    Returns:
        Dict with keys:
            - success (bool): Whether the job completed successfully
            - message (str): Human-readable result message
            - data (dict): Additional job data (signals found, trades executed, etc.)
            - error (str, optional): Error message if success=False
    """
    try:
        from backend.core.scheduler import scan_and_trade_job

        mode = str(payload.get("mode") or "paper")
        await scan_and_trade_job(mode)

        return {
            "success": True,
            "message": "Market scan completed successfully",
            "data": {"job_type": "market_scan", "params": payload},
        }

    except Exception as e:
        error_class = _classify_error(e)
        logger.error(f"market_scan handler error ({error_class}): {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "error_class": error_class,
            "message": f"Market scan failed: {str(e)}",
            "data": {"job_type": "market_scan", "params": payload},
        }


async def settlement_check(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for trade settlement job.

    Wraps the existing settlement_job logic from scheduler.py.
    Can be called from async worker context.

    Args:
        payload: Dict containing optional job parameters

    Returns:
        Dict with keys:
            - success (bool): Whether the job completed successfully
            - message (str): Human-readable result message
            - data (dict): Settlement data (trades settled, P&L, etc.)
            - error (str, optional): Error message if success=False
    """
    try:
        from backend.core.scheduler import settlement_job

        # Execute the settlement logic
        await settlement_job()

        return {
            "success": True,
            "message": "Settlement check completed successfully",
            "data": {"job_type": "settlement_check", "params": payload},
        }

    except Exception as e:
        error_class = _classify_error(e)
        logger.error(f"settlement_check handler error ({error_class}): {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "error_class": error_class,
            "message": f"Settlement check failed: {str(e)}",
            "data": {"job_type": "settlement_check", "params": payload},
        }


async def signal_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for signal generation job.

    Wraps signal scanning logic from the core signals module.
    Can be called from async worker context.

    Args:
        payload: Dict containing optional job parameters (e.g., market_type, strategy)

    Returns:
        Dict with keys:
            - success (bool): Whether the job completed successfully
            - message (str): Human-readable result message
            - data (dict): Signal generation data (signals found, etc.)
            - error (str, optional): Error message if success=False
    """
    try:
        from backend.core.signals import scan_for_signals

        # Execute signal generation logic
        signals = await scan_for_signals()

        # Extract signal stats
        actionable = [s for s in signals if s.passes_threshold]

        return {
            "success": True,
            "message": f"Signal generation completed: {len(signals)} signals, {len(actionable)} actionable",
            "data": {
                "job_type": "signal_generation",
                "total_signals": len(signals),
                "actionable_signals": len(actionable),
                "params": payload,
            },
        }

    except Exception as e:
        error_class = _classify_error(e)
        logger.error(f"signal_generation handler error ({error_class}): {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "error_class": error_class,
            "message": f"Signal generation failed: {str(e)}",
            "data": {"job_type": "signal_generation", "params": payload},
        }


async def weather_scan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for weather scan job.

    Wraps the weather_scan_and_trade_job logic from scheduling_strategies.py.
    Can be called from async worker context.

    Args:
        payload: Dict containing optional job parameters

    Returns:
        Dict with keys:
            - success (bool): Whether the job completed successfully
            - message (str): Human-readable result message
            - data (dict): Weather scan data (signals found, trades executed, etc.)
            - error (str, optional): Error message if success=False
    """
    try:
        from backend.core.scheduling_strategies import weather_scan_and_trade_job

        # Execute the weather scan logic in the requested mode, defaulting to paper
        # for queued jobs so worker-triggered scans never place live orders implicitly.
        await weather_scan_and_trade_job(mode=payload.get("mode", "paper"))

        return {
            "success": True,
            "message": "Weather scan completed successfully",
            "data": {"job_type": "weather_scan", "params": payload},
        }

    except Exception as e:
        error_class = _classify_error(e)
        logger.error(f"weather_scan handler error ({error_class}): {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "error_class": error_class,
            "message": f"Weather scan failed: {str(e)}",
            "data": {"job_type": "weather_scan", "params": payload},
        }
