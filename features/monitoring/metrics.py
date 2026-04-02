"""Expanded Prometheus Metrics Module
SCRI Platform v0.9.0 — comprehensive observability metrics.

This module extends the existing server/middleware/metrics.py with additional
domain-specific metrics for the SCRI platform:
  1. Request count by endpoint and status  (already in server middleware)
  2. Request latency histogram              (already in server middleware)
  3. Active scoring jobs gauge
  4. Data source health status
  5. Score computation duration
  6. Export as /metrics in Prometheus text format

The metrics here are designed to be collected by the existing MetricsMiddleware
and supplemented with domain-specific gauges and counters.
"""

import time
import threading
from collections import defaultdict
from datetime import datetime, timezone


# ===========================================================================
#  In-process metric stores (no external dependencies)
# ===========================================================================

class _Counter:
    """Thread-safe monotonic counter."""
    def __init__(self):
        self._lock = threading.Lock()
        self._values: dict[tuple, float] = defaultdict(float)

    def inc(self, labels: tuple = (), value: float = 1.0):
        with self._lock:
            self._values[labels] += value

    def items(self):
        with self._lock:
            return list(self._values.items())


class _Histogram:
    """Thread-safe histogram with fixed buckets."""
    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))

    def __init__(self, buckets=None):
        self._lock = threading.Lock()
        self._buckets = buckets or self.DEFAULT_BUCKETS
        # key -> {bucket_boundary: count, "_sum": float, "_count": int}
        self._data: dict[tuple, dict] = {}

    def observe(self, labels: tuple, value: float):
        with self._lock:
            if labels not in self._data:
                self._data[labels] = {b: 0 for b in self._buckets}
                self._data[labels]["_sum"] = 0.0
                self._data[labels]["_count"] = 0
            entry = self._data[labels]
            for b in self._buckets:
                if value <= b:
                    entry[b] += 1
            entry["_sum"] += value
            entry["_count"] += 1

    def items(self):
        with self._lock:
            return list(self._data.items())


class _Gauge:
    """Thread-safe gauge."""
    def __init__(self):
        self._lock = threading.Lock()
        self._values: dict[tuple, float] = defaultdict(float)

    def set(self, labels: tuple, value: float):
        with self._lock:
            self._values[labels] = value

    def inc(self, labels: tuple = (), value: float = 1.0):
        with self._lock:
            self._values[labels] += value

    def dec(self, labels: tuple = (), value: float = 1.0):
        with self._lock:
            self._values[labels] -= value

    def items(self):
        with self._lock:
            return list(self._values.items())


# ===========================================================================
#  Metric instances
# ===========================================================================

# 1. Request count by endpoint and status
request_count = _Counter()
# Labels: (method, endpoint, status_code)

# 2. Request latency histogram
request_latency = _Histogram(
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))
)
# Labels: (method, endpoint)

# 3. Active scoring jobs gauge
active_scoring_jobs = _Gauge()
# Labels: () — single global gauge

# 4. Data source health status (1 = up, 0 = down)
data_source_health = _Gauge()
# Labels: (source_name,)

# 5. Score computation duration histogram
score_computation_duration = _Histogram(
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf"))
)
# Labels: (location, dimension)

# 6. Misc counters/gauges
sanctions_screenings_total = _Counter()
# Labels: (matched,)

bom_analyses_total = _Counter()
# Labels: ()

cost_impact_estimates_total = _Counter()
# Labels: (scenario,)

forecast_requests_total = _Counter()
# Labels: (location, dimension)

alerts_dispatched_total = _Counter()
# Labels: (severity,)

active_monitors = _Gauge()
# Labels: ()


# ===========================================================================
#  Context manager for timing score computation
# ===========================================================================

class ScoreTimer:
    """Context manager that records score computation duration."""
    def __init__(self, location: str = "unknown", dimension: str = "overall"):
        self.location = location
        self.dimension = dimension
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        active_scoring_jobs.inc()
        return self

    def __exit__(self, *exc):
        duration = time.perf_counter() - self._start
        score_computation_duration.observe(
            (self.location, self.dimension), duration
        )
        active_scoring_jobs.dec()


# ===========================================================================
#  Record helpers  (called from API handlers)
# ===========================================================================

def record_request(method: str, endpoint: str, status_code: int, duration: float):
    """Record a single request metric."""
    request_count.inc((method, endpoint, str(status_code)))
    request_latency.observe((method, endpoint), duration)


def record_screening(matched: bool):
    sanctions_screenings_total.inc((str(matched).lower(),))


def record_bom_analysis():
    bom_analyses_total.inc()


def record_cost_estimate(scenario: str):
    cost_impact_estimates_total.inc((scenario,))


def record_forecast(location: str, dimension: str):
    forecast_requests_total.inc((location, dimension))


def record_alert(severity: str):
    alerts_dispatched_total.inc((severity,))


def set_data_source_health(source: str, is_up: bool):
    data_source_health.set((source,), 1.0 if is_up else 0.0)


def set_active_monitors(count: int):
    active_monitors.set((), float(count))


# ===========================================================================
#  Prometheus text-format exporter
# ===========================================================================

def _format_labels(label_names: list[str], label_values: tuple) -> str:
    """Format label set as Prometheus label string."""
    if not label_values or all(v == "" for v in label_values):
        return ""
    pairs = []
    for name, val in zip(label_names, label_values):
        escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
        pairs.append(f'{name}="{escaped}"')
    return "{" + ",".join(pairs) + "}"


def generate_metrics_text() -> str:
    """Generate Prometheus text exposition format for all SCRI metrics."""
    lines: list[str] = []
    now_ms = int(time.time() * 1000)

    # --- request_count ---
    lines.append("# HELP scri_http_requests_total Total HTTP requests (expanded).")
    lines.append("# TYPE scri_http_requests_total counter")
    for labels, val in request_count.items():
        lbl = _format_labels(["method", "endpoint", "status"], labels)
        lines.append(f"scri_http_requests_total{lbl} {val}")

    # --- request_latency ---
    lines.append("# HELP scri_http_request_duration_seconds HTTP request latency.")
    lines.append("# TYPE scri_http_request_duration_seconds histogram")
    for labels, data in request_latency.items():
        lbl_base = _format_labels(["method", "endpoint"], labels)
        cum = 0
        for b in request_latency._buckets:
            cum += data.get(b, 0)
            le = "+Inf" if b == float("inf") else str(b)
            lbl = _format_labels(["method", "endpoint", "le"], (*labels, le))
            lines.append(f"scri_http_request_duration_seconds_bucket{lbl} {cum}")
        lbl = _format_labels(["method", "endpoint"], labels)
        lines.append(f"scri_http_request_duration_seconds_sum{lbl} {data['_sum']:.6f}")
        lines.append(f"scri_http_request_duration_seconds_count{lbl} {data['_count']}")

    # --- active_scoring_jobs ---
    lines.append("# HELP scri_active_scoring_jobs Number of scoring jobs currently running.")
    lines.append("# TYPE scri_active_scoring_jobs gauge")
    for labels, val in active_scoring_jobs.items():
        lines.append(f"scri_active_scoring_jobs {val}")
    if not active_scoring_jobs.items():
        lines.append("scri_active_scoring_jobs 0")

    # --- data_source_health ---
    lines.append("# HELP scri_data_source_health Data source health (1=up, 0=down).")
    lines.append("# TYPE scri_data_source_health gauge")
    for labels, val in data_source_health.items():
        lbl = _format_labels(["source"], labels)
        lines.append(f"scri_data_source_health{lbl} {val}")

    # --- score_computation_duration ---
    lines.append("# HELP scri_score_computation_duration_seconds Time spent computing risk scores.")
    lines.append("# TYPE scri_score_computation_duration_seconds histogram")
    for labels, data in score_computation_duration.items():
        cum = 0
        for b in score_computation_duration._buckets:
            cum += data.get(b, 0)
            le = "+Inf" if b == float("inf") else str(b)
            lbl = _format_labels(["location", "dimension", "le"], (*labels, le))
            lines.append(f"scri_score_computation_duration_seconds_bucket{lbl} {cum}")
        lbl = _format_labels(["location", "dimension"], labels)
        lines.append(f"scri_score_computation_duration_seconds_sum{lbl} {data['_sum']:.6f}")
        lines.append(f"scri_score_computation_duration_seconds_count{lbl} {data['_count']}")

    # --- sanctions_screenings_total ---
    lines.append("# HELP scri_sanctions_screenings_total Sanctions screenings performed.")
    lines.append("# TYPE scri_sanctions_screenings_total counter")
    for labels, val in sanctions_screenings_total.items():
        lbl = _format_labels(["matched"], labels)
        lines.append(f"scri_sanctions_screenings_total{lbl} {val}")

    # --- bom_analyses_total ---
    lines.append("# HELP scri_bom_analyses_total BOM risk analyses performed.")
    lines.append("# TYPE scri_bom_analyses_total counter")
    total_bom = sum(v for _, v in bom_analyses_total.items())
    lines.append(f"scri_bom_analyses_total {total_bom}")

    # --- cost_impact_estimates_total ---
    lines.append("# HELP scri_cost_impact_estimates_total Cost impact estimates by scenario.")
    lines.append("# TYPE scri_cost_impact_estimates_total counter")
    for labels, val in cost_impact_estimates_total.items():
        lbl = _format_labels(["scenario"], labels)
        lines.append(f"scri_cost_impact_estimates_total{lbl} {val}")

    # --- forecast_requests_total ---
    lines.append("# HELP scri_forecast_requests_total Forecast requests by location.")
    lines.append("# TYPE scri_forecast_requests_total counter")
    for labels, val in forecast_requests_total.items():
        lbl = _format_labels(["location", "dimension"], labels)
        lines.append(f"scri_forecast_requests_total{lbl} {val}")

    # --- alerts_dispatched_total ---
    lines.append("# HELP scri_alerts_dispatched_total Alerts dispatched by severity.")
    lines.append("# TYPE scri_alerts_dispatched_total counter")
    for labels, val in alerts_dispatched_total.items():
        lbl = _format_labels(["severity"], labels)
        lines.append(f"scri_alerts_dispatched_total{lbl} {val}")

    # --- active_monitors ---
    lines.append("# HELP scri_active_monitors Number of actively monitored suppliers.")
    lines.append("# TYPE scri_active_monitors gauge")
    for labels, val in active_monitors.items():
        lines.append(f"scri_active_monitors {val}")
    if not active_monitors.items():
        lines.append("scri_active_monitors 0")

    lines.append("")
    return "\n".join(lines)
