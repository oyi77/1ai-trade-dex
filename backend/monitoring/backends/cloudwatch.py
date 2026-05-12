import os
import time
from typing import Dict

from backend.monitoring.backends.base import BaseMetricsBackend, MetricsBackendManifest
from backend.monitoring.backends.registry import plugin


@plugin
class CloudWatchBackend(BaseMetricsBackend):
    def __init__(self):
        self.namespace = os.environ.get("CW_NAMESPACE", "PolyEdge")
        self.enabled = True

        try:
            import boto3

            self._boto3_available = True
            self._client = None
        except ImportError:
            self._boto3_available = False

    @classmethod
    def manifest(cls) -> MetricsBackendManifest:
        return MetricsBackendManifest(
            name="cloudwatch",
            display_name="AWS CloudWatch",
            version="1.0.0",
            required_env_vars=["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
            tags=["metrics", "aws", "cloud"],
        )

    def _get_client(self):
        if not self._boto3_available:
            return None
        if self._client is None:
            import boto3

            self._client = boto3.client("cloudwatch")
        return self._client

    async def increment_counter(self, name: str, value: int = 1, tags: dict = None) -> None:
        if not self._boto3_available:
            return
        await self._send_metric("Count", name, float(value), tags or {})

    async def record_gauge(self, name: str, value: float, tags: dict = None) -> None:
        if not self._boto3_available:
            return
        await self._send_metric("Gauge", name, value, tags or {})

    async def record_histogram(self, name: str, value: float, tags: dict = None) -> None:
        if not self._boto3_available:
            return
        await self._send_metric("Summary", name, value, tags or {})

    async def _send_metric(self, metric_type: str, name: str, value: float, tags: Dict[str, str]) -> None:
        client = self._get_client()
        if client is None:
            return

        try:
            dimensions = [{"Name": k, "Value": v} for k, v in tags.items()]

            client.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        "MetricName": name,
                        "Timestamp": time.time(),
                        "Value": value,
                        "Unit": metric_type,
                        "Dimensions": dimensions,
                    }
                ],
            )
        except Exception:
            pass

    async def health_check(self) -> bool:
        return self._boto3_available
