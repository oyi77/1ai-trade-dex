# state.py — extracted from scheduler.py
"""Scheduler sub-module: state."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from backend.core.scheduling.task_manager import TaskManager
from backend.job_queue.abstract import AbstractQueue, create_queue
from backend.job_queue.worker import Worker
from typing import List, Optional
import asyncio
import threading

scheduler: Optional[AsyncIOScheduler] = None

queue: Optional[AbstractQueue] = None

worker: Optional[Worker] = None

worker_task: Optional[asyncio.Task] = None

task_manager: Optional[TaskManager] = None

_scheduler_state_lock = threading.Lock()

def _get_scheduler() -> Optional[AsyncIOScheduler]:
    """Thread-safe accessor for the module-level scheduler."""
    with _scheduler_state_lock:
        return scheduler

def _set_scheduler(value: Optional[AsyncIOScheduler]) -> None:
    """Thread-safe setter for the module-level scheduler."""
    global scheduler
    with _scheduler_state_lock:
        scheduler = value