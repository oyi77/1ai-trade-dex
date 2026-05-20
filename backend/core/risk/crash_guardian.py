"""Crash guardian -- monitors PM2-managed processes and triggers restarts.

Detects segfaults, memory leaks, and abnormal exits that PM2's built-in
autorestart may miss (e.g. max_restarts exhausted, zombie processes).
Runs as a lightweight async loop inside the bot process.

Complements scripts/bot-guardian.sh which monitors from outside.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from loguru import logger

_MONITORED_PROCESSES = ("polyedge-bot", "polyedge-api")
_PM2_TIMEOUT = 10
_CHECK_INTERVAL = 30
_MEMORY_WARN_MB = 1024
_MEMORY_RESTART_MB = 2048
_MAX_UNHEALTHY_CHECKS = 3


@dataclass
class ProcessHealth:
    name: str
    pid: int = 0
    status: str = "unknown"
    restart_count: int = 0
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    unhealthy_streak: int = 0
    last_restart_at: float = 0.0
    last_check_at: float = 0.0


@dataclass
class CrashGuardian:
    """Monitors PM2 processes and triggers restarts on crash/OOM/segfault."""

    check_interval: float = _CHECK_INTERVAL
    memory_warn_mb: float = _MEMORY_WARN_MB
    memory_restart_mb: float = _MEMORY_RESTART_MB
    max_unhealthy_checks: int = _MAX_UNHEALTHY_CHECKS
    _running: bool = False
    _processes: Dict[str, ProcessHealth] = field(default_factory=dict)
    _task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._loop())
        logger.info("[CrashGuardian] Started -- monitoring %s", _MONITORED_PROCESSES)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.exception("[CrashGuardian] task cancelled unexpectedly")
        logger.info("[CrashGuardian] Stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_all_processes()
            except Exception:
                logger.exception("[CrashGuardian] Error in monitoring loop")
            await asyncio.sleep(self.check_interval)

    async def _check_all_processes(self) -> None:
        now = time.time()
        for proc_name in _MONITORED_PROCESSES:
            health = await self._get_process_health(proc_name)
            if health is None:
                continue

            prev = self._processes.get(proc_name)
            if prev:
                health.unhealthy_streak = prev.unhealthy_streak
            self._processes[proc_name] = health

            if prev and health.restart_count > prev.restart_count:
                delta = health.restart_count - prev.restart_count
                logger.warning(
                    "[CrashGuardian] %s restarted %d time(s) since last check "
                    "(total: %d, status: %s)",
                    proc_name,
                    delta,
                    health.restart_count,
                    health.status,
                )

            is_unhealthy = False

            if health.memory_mb > self.memory_restart_mb:
                is_unhealthy = True
                health.unhealthy_streak += 1
                logger.warning(
                    "[CrashGuardian] %s memory %.0f MB > %d MB (streak: %d/%d)",
                    proc_name,
                    health.memory_mb,
                    self.memory_restart_mb,
                    health.unhealthy_streak,
                    self.max_unhealthy_checks,
                )
                if health.unhealthy_streak >= self.max_unhealthy_checks:
                    await self._restart_process(proc_name, reason="memory_leak")
                    health.unhealthy_streak = 0
                    health.last_restart_at = now
                    is_unhealthy = False
            elif health.memory_mb > self.memory_warn_mb:
                logger.warning(
                    "[CrashGuardian] %s memory %.0f MB approaching limit",
                    proc_name,
                    health.memory_mb,
                )

            if health.status in ("stopped", "errored"):
                is_unhealthy = True
                health.unhealthy_streak += 1
                logger.warning(
                    "[CrashGuardian] %s status=%s (streak: %d/%d)",
                    proc_name,
                    health.status,
                    health.unhealthy_streak,
                    self.max_unhealthy_checks,
                )
                if health.unhealthy_streak >= self.max_unhealthy_checks:
                    await self._restart_process(
                        proc_name, reason="status_" + health.status
                    )
                    health.unhealthy_streak = 0
                    health.last_restart_at = now

            if not is_unhealthy:
                health.unhealthy_streak = 0

            health.last_check_at = now

    async def _get_process_health(self, proc_name: str) -> Optional[ProcessHealth]:
        try:
            data = await asyncio.to_thread(self._pm2_jlist)
            if data is None:
                return None
            for p in data:
                if p.get("name") == proc_name:
                    pm2_env = p.get("pm2_env", {})
                    monit = p.get("monit", {})
                    return ProcessHealth(
                        name=proc_name,
                        pid=p.get("pid", 0),
                        status=pm2_env.get("status", "unknown"),
                        restart_count=pm2_env.get("restart_time", 0),
                        memory_mb=(monit.get("memory", 0) or 0) / (1024 * 1024),
                        cpu_percent=monit.get("cpu", 0) or 0,
                    )
            logger.warning("[CrashGuardian] Process %s not found in PM2", proc_name)
            return None
        except Exception:
            logger.exception("[CrashGuardian] Failed to query PM2 for %s", proc_name)
            return None

    @staticmethod
    def _pm2_jlist() -> Optional[list]:
        try:
            result = subprocess.run(
                ["pm2", "jlist"],
                capture_output=True,
                text=True,
                timeout=_PM2_TIMEOUT,
            )
            if result.returncode != 0:
                logger.warning(
                    "[CrashGuardian] pm2 jlist failed: %s", result.stderr.strip()
                )
                return None
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("[CrashGuardian] pm2 jlist timed out")
            return None
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning("[CrashGuardian] pm2 jlist error: %s", e)
            return None

    async def _restart_process(self, proc_name: str, reason: str) -> None:
        logger.error("[CrashGuardian] RESTARTING %s -- reason: %s", proc_name, reason)
        try:
            proc = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["pm2", "restart", proc_name, "--update-env"],
                    capture_output=True,
                    text=True,
                    timeout=_PM2_TIMEOUT,
                )
            )
            if proc.returncode == 0:
                logger.info("[CrashGuardian] Successfully restarted %s", proc_name)
            else:
                logger.error(
                    "[CrashGuardian] pm2 restart failed for %s: %s",
                    proc_name,
                    proc.stderr.strip(),
                )
        except Exception:
            logger.exception("[CrashGuardian] Failed to restart %s", proc_name)

    @property
    def status(self) -> Dict:
        return {
            name: {
                "pid": h.pid,
                "status": h.status,
                "restart_count": h.restart_count,
                "memory_mb": round(h.memory_mb, 1),
                "cpu_percent": round(h.cpu_percent, 1),
                "unhealthy_streak": h.unhealthy_streak,
                "last_check_at": h.last_check_at,
            }
            for name, h in self._processes.items()
        }


crash_guardian = CrashGuardian()
