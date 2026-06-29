import os

import sentry_sdk
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "splitapp_http_requests_total",
    "Total HTTP requests handled by SplitApp backend.",
    ["method", "path", "status_code"],
)
REQUEST_DURATION = Histogram(
    "splitapp_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
)


def init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    sentry_sdk.init(dsn=dsn)


def record_request_metrics(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    REQUEST_COUNT.labels(method=method, path=path, status_code=str(status_code)).inc()
    REQUEST_DURATION.labels(method=method, path=path).observe(duration_seconds)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
