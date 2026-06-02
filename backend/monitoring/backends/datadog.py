import os
from typing import Dict

from backend.monitoring.backends.base import BaseMetricsBackend, MetricsBackendManifest
from backend.monitoring.backends.registry import plugin


@plugin
class DatadogBackend(BaseMetricsBackend):
    def __init__(self):
        self.api_key = os.environ.get("DATADOG_API_KEY", "")
        self.enabled = bool(self.api_key)

    @classmethod
    def manifest(cls) -> MetricsBackendManifest:
        return MetricsBackendManifest(
            name="datadog",
            display_name="Datadog",
            version="1.0.0",
            required_env_vars=["DATADOG_API_KEY"],
            tags=["metrics", "commercial"],
        )

    async def increment_counter(
        self, name: str, value: int = 1, tags: dict = None
    ) -> None:
        if not self.enabled:
            return
        await self._send_metric("count", name, float(value), tags or {})

    async def record_gauge(self, name: str, value: float, tags: dict = None) -> None:
        if not self.enabled:
            return
        await self._send_metric("gauge", name, value, tags or {})

    async def record_histogram(
        self, name: str, value: float, tags: dict = None
    ) -> None:
        if not self.enabled:
            return
        await self._send_metric("histogram", name, value, tags or {})

    async def _send_metric(
        self, metric_type: str, name: str, value: float, tags: Dict[str, str]
    ) -> None:
        import aiohttp

        if not self.enabled:
            return

        payload = {
            "series": [
                {
                    "metric": name,
                    "points": [
                        {"value": value, "timestamp": int(__import__("time").time())}
                    ],
                    "type": metric_type,
                    "tags": [f"{k}:{v}" for k, v in tags.items()],
                }
            ]
        }

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                headers = {
                    "DD-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                }
                async with session.post(
                    "https://api.datadoghq.com/api/v1/series",
                    headers=headers,
                    json=payload,
                    timeout=5,
                ) as response:
                    response.raise_for_status()
        except Exception:
            import logging
            logging.getLogger(__name__).debug("datadog: failed to send metric")

    async def health_check(self) -> bool:
        return self.enabled
