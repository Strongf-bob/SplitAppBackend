import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Callable, TypeVar

import sentry_sdk
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

F = TypeVar("F", bound=Callable)

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
SERVICE_OPERATION_COUNT = Counter(
    "splitapp_service_operations_total",
    "Total service operations handled by SplitApp backend.",
    ["operation", "status"],
)
SERVICE_OPERATION_DURATION = Histogram(
    "splitapp_service_operation_duration_seconds",
    "Service operation duration in seconds.",
    ["operation"],
)
DB_OPERATION_COUNT = Counter(
    "splitapp_db_operations_total",
    "Total database operations handled by SplitApp backend.",
    ["operation", "status"],
)
DB_OPERATION_DURATION = Histogram(
    "splitapp_db_operation_duration_seconds",
    "Database operation duration in seconds.",
    ["operation"],
)
DOMAIN_EVENT_COUNT = Counter(
    "splitapp_domain_events_total",
    "Total SplitApp domain events recorded by backend services.",
    ["domain", "action"],
)
MONEY_AMOUNT = Histogram(
    "splitapp_money_amount",
    "Observed money amounts handled by SplitApp backend.",
    ["kind"],
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, float("inf")),
)
EVENT_PARTICIPANT_COUNT = Histogram(
    "splitapp_event_participants",
    "Observed participant counts on event mutations.",
    buckets=(1, 2, 3, 4, 5, 8, 13, 21, 34, float("inf")),
)
COLLECTION_DOCUMENT_COUNT = Gauge(
    "splitapp_collection_documents",
    "Current MongoDB document counts for key SplitApp collections.",
    ["collection", "state"],
)
RECEIPT_IMAGE_PREPROCESSING_COUNT = Counter(
    "splitapp_receipt_image_preprocessing_total",
    "Receipt image preprocessing outcomes before Splitik vision requests.",
    ["outcome", "selected_variant"],
)
RECEIPT_IMAGE_PREPROCESSING_DURATION = Histogram(
    "splitapp_receipt_image_preprocessing_duration_seconds",
    "CPU time spent preprocessing receipt images.",
    ["selected_variant"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, float("inf")),
)


def init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    sentry_sdk.init(dsn=dsn)


def record_request_metrics(
    method: str, path: str, status_code: int, duration_seconds: float
) -> None:
    REQUEST_COUNT.labels(method=method, path=path, status_code=str(status_code)).inc()
    REQUEST_DURATION.labels(method=method, path=path).observe(duration_seconds)


def record_domain_event(domain: str, action: str) -> None:
    DOMAIN_EVENT_COUNT.labels(domain=domain, action=action).inc()


def record_receipt_image_preprocessing(
    *, outcome: str, selected_variant: str, duration_seconds: float
) -> None:
    RECEIPT_IMAGE_PREPROCESSING_COUNT.labels(
        outcome=outcome,
        selected_variant=selected_variant,
    ).inc()
    RECEIPT_IMAGE_PREPROCESSING_DURATION.labels(selected_variant=selected_variant).observe(
        max(0, duration_seconds)
    )


def observe_money_amount(kind: str, amount: object) -> None:
    MONEY_AMOUNT.labels(kind=kind).observe(float(amount))


def observe_event_participants(count: int) -> None:
    EVENT_PARTICIPANT_COUNT.observe(count)


def refresh_database_metrics(db) -> None:
    collection_names = ("users", "events", "receipts", "payments", "audit_events")
    for collection_name in collection_names:
        collection = getattr(db, collection_name)
        if collection_name == "users" or collection_name == "audit_events":
            COLLECTION_DOCUMENT_COUNT.labels(collection=collection_name, state="all").set(
                collection.count_documents({})
            )
            continue

        COLLECTION_DOCUMENT_COUNT.labels(collection=collection_name, state="active").set(
            collection.count_documents({"deleted_at": {"$exists": False}})
        )
        COLLECTION_DOCUMENT_COUNT.labels(collection=collection_name, state="deleted").set(
            collection.count_documents({"deleted_at": {"$exists": True}})
        )


@contextmanager
def monitor_service_operation(operation: str) -> Iterator[None]:
    started = time.monotonic()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration_seconds = time.monotonic() - started
        SERVICE_OPERATION_COUNT.labels(operation=operation, status=status).inc()
        SERVICE_OPERATION_DURATION.labels(operation=operation).observe(duration_seconds)


@contextmanager
def monitor_db_operation(operation: str) -> Iterator[None]:
    started = time.monotonic()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration_seconds = time.monotonic() - started
        DB_OPERATION_COUNT.labels(operation=operation, status=status).inc()
        DB_OPERATION_DURATION.labels(operation=operation).observe(duration_seconds)


def track_service_operation(operation: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with monitor_service_operation(operation):
                return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
