"""Prometheus Metrics Collection Middleware
SCRI Platform operations monitoring via prometheus_client.
"""
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

scri_requests_total = Counter(
    "scri_requests_total",
    "Total HTTP requests served by the SCRI API",
    ["method", "endpoint", "status"],
)

scri_request_duration_seconds = Histogram(
    "scri_request_duration_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

scri_active_alerts = Gauge(
    "scri_active_alerts",
    "Number of active risk alerts in the last 24 h",
)

scri_data_sources_up = Gauge(
    "scri_data_sources_up",
    "Number of external data sources currently reachable",
)

# Simple in-process request counter (used by /health)
_total_requests_served: int = 0


def get_total_requests_served() -> int:
    """Return the total number of requests served since process start."""
    return _total_requests_served


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect per-request Prometheus metrics."""

    async def dispatch(self, request: Request, call_next):
        global _total_requests_served

        # Normalise the endpoint label so high-cardinality path params
        # don't explode the metric series.
        path = request.url.path
        endpoint = self._normalise_path(path)
        method = request.method

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        status = str(response.status_code)

        scri_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        scri_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)
        _total_requests_served += 1

        return response

    @staticmethod
    def _normalise_path(path: str) -> str:
        """Replace variable path segments with placeholders."""
        parts = path.strip("/").split("/")
        normalised = []
        skip_next = False
        for i, part in enumerate(parts):
            if skip_next:
                normalised.append("{id}")
                skip_next = False
                continue
            # Heuristic: segment after 'risk', 'forecast', etc. is an id
            if part in ("risk", "forecast", "timeseries", "benchmark"):
                normalised.append(part)
                skip_next = True
                continue
            normalised.append(part)
        return "/" + "/".join(normalised) if normalised else "/"


def metrics_response() -> Response:
    """Generate a Prometheus-compatible /metrics response."""
    body = generate_latest()
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
