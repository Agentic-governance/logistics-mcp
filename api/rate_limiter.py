"""In-Memory Rate Limiter for SCRI Platform v0.9.0

A simple, dependency-free rate limiter using the sliding-window counter
algorithm. Designed as a lightweight complement to slowapi for endpoints
where the decorator approach is not convenient (e.g., sub-routers).

Usage:
    from api.rate_limiter import RateLimiter, RateLimitExceededError

    limiter = RateLimiter()

    # In a request handler:
    try:
        limiter.check("client_ip", "general")
    except RateLimitExceededError as e:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded", "retry_after": e.retry_after},
            headers={"Retry-After": str(e.retry_after)},
        )
"""

import time
import threading
from collections import defaultdict
from typing import Optional


class RateLimitExceededError(Exception):
    """Raised when a client exceeds the configured rate limit."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after}s.")


class RateLimiter:
    """Thread-safe sliding-window rate limiter (no external dependencies).

    Tiers:
        - "general"  : 60 requests per minute (most endpoints)
        - "heavy"    : 10 requests per minute (BOM, cost-impact, screening, Monte Carlo)
        - "screening": 30 requests per minute (sanctions screening)
    """

    DEFAULT_LIMITS = {
        "general": (60, 60),      # (max_requests, window_seconds)
        "heavy": (10, 60),
        "screening": (30, 60),
    }

    def __init__(self, limits: Optional[dict] = None):
        self._limits = limits or self.DEFAULT_LIMITS
        self._lock = threading.Lock()
        # key -> list of timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 120  # seconds

    def check(self, client_id: str, tier: str = "general") -> bool:
        """Check if the request is allowed. Raises RateLimitExceededError if not.

        Args:
            client_id: Unique client identifier (typically IP address)
            tier: Rate limit tier ("general", "heavy", "screening")

        Returns:
            True if the request is allowed

        Raises:
            RateLimitExceededError: If rate limit is exceeded
        """
        max_requests, window_seconds = self._limits.get(tier, self.DEFAULT_LIMITS["general"])
        now = time.monotonic()
        bucket_key = f"{client_id}:{tier}"

        with self._lock:
            # Periodic cleanup of old entries
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup(now)
                self._last_cleanup = now

            # Prune old timestamps from this bucket
            window_start = now - window_seconds
            timestamps = self._windows[bucket_key]
            self._windows[bucket_key] = [t for t in timestamps if t > window_start]
            timestamps = self._windows[bucket_key]

            if len(timestamps) >= max_requests:
                # Calculate retry-after from the oldest entry in the window
                oldest = timestamps[0]
                retry_after = int(oldest + window_seconds - now) + 1
                raise RateLimitExceededError(retry_after=max(retry_after, 1))

            timestamps.append(now)
            return True

    def _cleanup(self, now: float):
        """Remove stale entries to prevent memory growth."""
        stale_keys = []
        for key, timestamps in self._windows.items():
            # Determine the window for this key
            tier = key.rsplit(":", 1)[-1] if ":" in key else "general"
            _, window_seconds = self._limits.get(tier, self.DEFAULT_LIMITS["general"])
            window_start = now - window_seconds
            self._windows[key] = [t for t in timestamps if t > window_start]
            if not self._windows[key]:
                stale_keys.append(key)
        for key in stale_keys:
            del self._windows[key]

    def get_remaining(self, client_id: str, tier: str = "general") -> int:
        """Get the number of remaining requests in the current window."""
        max_requests, window_seconds = self._limits.get(tier, self.DEFAULT_LIMITS["general"])
        now = time.monotonic()
        bucket_key = f"{client_id}:{tier}"

        with self._lock:
            window_start = now - window_seconds
            timestamps = [t for t in self._windows.get(bucket_key, []) if t > window_start]
            return max(0, max_requests - len(timestamps))


# --- Classify endpoints by tier ---

HEAVY_ENDPOINTS = {
    "/api/v1/bom/analyze",
    "/api/v1/bom/infer-supply-chain",
    "/api/v1/bom/hidden-risk",
    "/api/v1/bom/import-csv",
    "/api/v1/cost-impact/estimate",
    "/api/v1/cost-impact/compare",
    "/api/v1/cost-impact/sensitivity",
    "/api/v1/screening/reputation",
    "/api/v1/screening/reputation/batch",
    "/api/v1/bulk-assess",
    "/api/v1/analytics/portfolio",
    "/api/v1/analytics/sensitivity/montecarlo",
    "/api/v1/analytics/correlations",
    "/api/v1/analytics/correlations/leading-indicators",
    "/api/v1/analytics/benchmark/industry",
    "/api/v1/analytics/benchmark/peers",
    "/api/v1/analytics/sensitivity/weights",
    "/api/v1/analytics/sensitivity/what-if",
    "/api/v1/analytics/sensitivity/threshold",
    "/api/v1/dd-report",
    "/api/v1/concentration",
}

SCREENING_ENDPOINTS = {
    "/api/v1/screen",
    "/api/v1/screen/bulk",
}


def classify_endpoint(path: str) -> str:
    """Classify an endpoint path into a rate-limit tier."""
    # Normalize path (strip trailing slash)
    path = path.rstrip("/")

    if path in HEAVY_ENDPOINTS:
        return "heavy"
    if path in SCREENING_ENDPOINTS:
        return "screening"

    # Check prefix patterns for heavy endpoints
    for prefix in ("/api/v1/bom/", "/api/v1/cost-impact/", "/api/v1/screening/"):
        if path.startswith(prefix):
            return "heavy"

    return "general"
