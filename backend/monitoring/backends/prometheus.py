from backend.monitoring.backends.base import BaseMetricsBackend, MetricsBackendManifest
from backend.monitoring.backends.registry import plugin
from backend.monitoring.metrics import _metrics_lock, _metrics


@plugin
class PrometheusBackend(BaseMetricsBackend):
    @classmethod
    def manifest(cls) -> MetricsBackendManifest:
        return MetricsBackendManifest(
            name="prometheus",
            display_name="Prometheus",
            version="1.0.0",
            required_env_vars=[],
            tags=["metrics", "open-source"],
        )

    async def increment_counter(
        self, name: str, value: int = 1, tags: dict = None
    ) -> None:
        with _metrics_lock:
            _metrics[name] = _metrics.get(name, 0) + value

    async def record_gauge(self, name: str, value: float, tags: dict = None) -> None:
        with _metrics_lock:
            _metrics[name] = value

    async def record_histogram(
        self, name: str, value: float, tags: dict = None
    ) -> None:
        with _metrics_lock:
            if "histograms" not in _metrics:
                _metrics["histograms"] = {}
            if name not in _metrics["histograms"]:
                _metrics["histograms"][name] = []
            _metrics["histograms"][name].append(value)
            if len(_metrics["histograms"][name]) > 1000:
                _metrics["histograms"][name] = _metrics["histograms"][name][-1000:]
