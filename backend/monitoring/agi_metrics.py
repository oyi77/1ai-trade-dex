"""AGI component Prometheus metrics (ADR-014).

Provides observability for all AGI subsystems: cognitive core, evolution,
agent council, learning pipeline, and correlation monitoring.

All metrics use the ``polyedge_agi_`` prefix per project conventions.
"""

import functools
import time

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Cognitive Core metrics
# ---------------------------------------------------------------------------

cognitive_core_request_latency = Histogram(
    "polyedge_agi_cognitive_core_request_latency_seconds",
    "Cognitive core request latency (remember/recall/forget)",
    ["operation"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

cognitive_core_recall_hit_rate = Gauge(
    "polyedge_agi_cognitive_core_recall_hit_rate",
    "Recall hit rate (0-1) from the cognitive core",
)

cognitive_core_memory_size = Gauge(
    "polyedge_agi_cognitive_core_memory_size",
    "Total memories stored in the cognitive core",
)

cognitive_core_health = Gauge(
    "polyedge_agi_cognitive_core_health",
    "Cognitive core health status (1=online, 0.5=amnesia, 0=offline)",
)

# ---------------------------------------------------------------------------
# Evolution harness metrics
# ---------------------------------------------------------------------------

evolution_population_size = Gauge(
    "polyedge_agi_evolution_population_size",
    "Current evolution population size",
)

evolution_fitness_best = Gauge(
    "polyedge_agi_evolution_fitness_best",
    "Best fitness score in the current population",
)

evolution_fitness_avg = Gauge(
    "polyedge_agi_evolution_fitness_avg",
    "Average fitness score in the current population",
)

evolution_cycle_duration = Histogram(
    "polyedge_agi_evolution_cycle_duration_seconds",
    "Evolution cycle (evolve call) wall-clock duration",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

evolution_generation = Gauge(
    "polyedge_agi_evolution_generation",
    "Current evolution generation number",
)

evolution_pareto_front_size = Gauge(
    "polyedge_agi_evolution_pareto_front_size",
    "Number of individuals on the Pareto front",
)

# ---------------------------------------------------------------------------
# Agent council metrics
# ---------------------------------------------------------------------------

council_message_total = Counter(
    "polyedge_agi_council_message_total",
    "Total messages dispatched through the council bus",
    ["source_agent", "target_agent", "message_type"],
)

council_agent_response_time = Histogram(
    "polyedge_agi_council_agent_response_time_seconds",
    "Agent message handling latency",
    ["agent"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

council_queue_depth = Gauge(
    "polyedge_agi_council_queue_depth",
    "Number of pending messages in the council bus",
)

council_authority_rejections = Counter(
    "polyedge_agi_council_authority_rejection_total",
    "Messages suppressed by authority hierarchy",
    ["source_agent", "message_type"],
)

# ---------------------------------------------------------------------------
# Learning pipeline metrics
# ---------------------------------------------------------------------------

pipeline_processing_time = Histogram(
    "polyedge_agi_pipeline_processing_time_seconds",
    "Learning pipeline settlement processing time",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

pipeline_lessons_stored = Counter(
    "polyedge_agi_pipeline_lessons_stored_total",
    "Total trade lessons stored in the brain",
)

pipeline_errors = Counter(
    "polyedge_agi_pipeline_errors_total",
    "Learning pipeline errors by stage",
    ["stage"],
)

# ---------------------------------------------------------------------------
# Correlation monitor metrics (enhanced from existing)
# ---------------------------------------------------------------------------

correlation_exposure_pct = Gauge(
    "polyedge_agi_correlation_exposure_pct",
    "Correlation-adjusted exposure as percentage of bankroll, by category",
    ["category"],
)

correlation_blocked_total = Counter(
    "polyedge_agi_correlation_blocked_total",
    "Total trades blocked by correlation monitor",
)

# ---------------------------------------------------------------------------
# Signal latency instrumentation (ADR-014: p99 < 500ms target)
# ---------------------------------------------------------------------------

signal_end_to_end_latency = Histogram(
    "polyedge_agi_signal_e2e_latency_seconds",
    "End-to-end signal generation latency (strategy -> risk -> order)",
    ["strategy"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def record_cognitive_core_latency(operation: str, duration_s: float) -> None:
    """Record a cognitive core operation latency."""
    cognitive_core_request_latency.labels(operation=operation).observe(duration_s)


def record_cognitive_core_recall_stats(hit_rate: float, memory_size: int) -> None:
    """Update cognitive core recall hit rate and memory size gauges."""
    cognitive_core_recall_hit_rate.set(hit_rate)
    cognitive_core_memory_size.set(memory_size)


def set_cognitive_core_health(status: str) -> None:
    """Set cognitive core health gauge from status string."""
    mapping = {"online": 1.0, "amnesia": 0.5, "offline": 0.0}
    cognitive_core_health.set(mapping.get(status, 0.0))


def record_evolution_stats(
    population_size: int,
    best_fitness: float,
    avg_fitness: float,
    generation: int = 0,
    pareto_front_size: int = 0,
) -> None:
    """Update evolution harness gauges."""
    evolution_population_size.set(population_size)
    evolution_fitness_best.set(best_fitness)
    evolution_fitness_avg.set(avg_fitness)
    evolution_generation.set(generation)
    evolution_pareto_front_size.set(pareto_front_size)


def record_evolution_cycle(duration_s: float) -> None:
    """Record evolution cycle wall-clock duration."""
    evolution_cycle_duration.observe(duration_s)


def record_council_message(
    source: str, target: str, message_type: str, count: int = 1
) -> None:
    """Increment council message counter."""
    council_message_total.labels(
        source_agent=source, target_agent=target, message_type=message_type
    ).inc(count)


def record_council_response_time(agent: str, duration_s: float) -> None:
    """Record an agent's message handling latency."""
    council_agent_response_time.labels(agent=agent).observe(duration_s)


def set_council_queue_depth(depth: int) -> None:
    """Set the current council queue depth."""
    council_queue_depth.set(depth)


def record_council_authority_rejection(source: str, message_type: str) -> None:
    """Record a message suppressed by authority hierarchy."""
    council_authority_rejections.labels(
        source_agent=source, message_type=message_type
    ).inc()


def record_pipeline_processing(duration_s: float) -> None:
    """Record learning pipeline processing time."""
    pipeline_processing_time.observe(duration_s)


def record_pipeline_lesson_stored(count: int = 1) -> None:
    """Increment lessons stored counter."""
    pipeline_lessons_stored.inc(count)


def record_pipeline_error(stage: str) -> None:
    """Record a pipeline error for the given stage."""
    pipeline_errors.labels(stage=stage).inc()


def record_correlation_exposure(category: str, pct: float) -> None:
    """Set correlation exposure gauge for a category."""
    correlation_exposure_pct.labels(category=category).set(pct)


def record_correlation_blocked() -> None:
    """Increment correlation blocked counter."""
    correlation_blocked_total.inc()


def record_signal_e2e_latency(strategy: str, duration_s: float) -> None:
    """Record end-to-end signal latency for ADR-014 p99 tracking."""
    signal_end_to_end_latency.labels(strategy=strategy).observe(duration_s)


# ---------------------------------------------------------------------------
# Decorator for tracing signal latency (mirrors hft_metrics.trace_latency)
# ---------------------------------------------------------------------------


def trace_agi_latency(func):
    """Decorator that records signal end-to-end latency to Prometheus.

    Works on both sync and async methods. Strategy name is read from
    ``self.name`` on the bound instance.
    """
    if func.__code__.co_flags & 0x80:  # CO_COROUTINE

        @functools.wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            start = time.monotonic()
            try:
                return await func(self, *args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                sname = getattr(self, "name", self.__class__.__name__)
                record_signal_e2e_latency(sname, elapsed)

        return async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            start = time.monotonic()
            try:
                return func(self, *args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                sname = getattr(self, "name", self.__class__.__name__)
                record_signal_e2e_latency(sname, elapsed)

        return sync_wrapper
