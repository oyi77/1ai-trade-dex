"""
PolyEdge entry point.

Run with:
    python -m backend

Starts the full orchestrator: weather scanner, copy trader, Telegram bot,
CLOB execution, and APScheduler jobs.
"""
import asyncio
import fcntl
import os
import sys

from backend.core.orchestrator import main

LOCK_FILE = "/tmp/polyedge.lock"


def acquire_lock():
    """Acquire exclusive process lock. Exit if another instance is running."""
    fp = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fp.write(str(os.getpid()))
        fp.flush()
        return fp  # Must keep reference to prevent GC closing the file
    except IOError:
        print("ERROR: Another PolyEdge instance is already running. Exiting.")
        sys.exit(1)


if __name__ == "__main__":
    _lock_fp = acquire_lock()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
