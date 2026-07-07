import os
import redis as redis_lib
from decouple import config
from prometheus_client import Counter, Histogram, REGISTRY
from prometheus_client.core import GaugeMetricFamily

webhook_requests_total = Counter(
    "webhook_requests_total",
    "Total webhook requests by routing outcome",
    ["status"],
)

enrichment_duration_seconds = Histogram(
    "enrichment_duration_seconds",
    "LLM call latency in seconds",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

enrichment_status_total = Counter(
    "enrichment_status_total",
    "Enrichment terminal state counts",
    ["status"],
)

reconciliation_requeued_total = Counter(
    "reconciliation_requeued_total",
    "Total enrichments re-queued by reconciliation job",
)

agent_iterations = Histogram(
    "agent_iterations",
    "Number of loop iterations per investigation",
    buckets=[0, 1, 2, 3],
)

agent_tool_calls_total = Counter(
    "agent_tool_calls_total",
    "Total tool calls made during investigation loops",
    ["tool"],
)


class _CircuitBreakerCollector:

    def collect(self):

        try:
            r = redis_lib.from_url(config("REDIS_URL", default="redis://localhost:6379/0"))
            
            # fetch
            data = r.hgetall("circuit_breaker:llm")
            state = data.get(b"state", b"CLOSED").decode() if data else "CLOSED"

            # encode
            value = 1.0 if state == "OPEN" else 0.0
        except Exception:
            value = 0.0

        g = GaugeMetricFamily("circuit_breaker_state", "Circuit breaker state (0=CLOSED 1=OPEN)")
        g.add_metric([], value)
        yield g


class _CeleryQueueDepthCollector:

    def collect(self):

        try:
            r = redis_lib.from_url(config("REDIS_URL", default="redis://localhost:6379/0"))

            # depth
            depth = float(r.llen("celery"))

        except Exception:
            depth = 0.0

        g = GaugeMetricFamily("celery_queue_depth", "Number of tasks in Celery default queue")
        g.add_metric([], depth)
        yield g


# single
if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    REGISTRY.register(_CircuitBreakerCollector())
    REGISTRY.register(_CeleryQueueDepthCollector())
