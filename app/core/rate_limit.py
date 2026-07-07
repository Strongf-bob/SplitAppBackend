import os
import threading
import time

from fastapi import HTTPException, status

_LOCK = threading.Lock()
_REQUEST_TIMESTAMPS: dict[tuple[str, str], list[float]] = {}
_IN_FLIGHT: dict[tuple[str, str], int] = {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def check_rate_limit(
    scope: str,
    actor_key: str,
    *,
    max_requests: int | None = None,
    window_seconds: int | None = None,
    detail: str = "Too many requests.",
) -> None:
    if not _enabled():
        return

    max_requests = max(1, max_requests or _env_int("RATE_LIMIT_MAX_REQUESTS", 30))
    window_seconds = max(1, window_seconds or _env_int("RATE_LIMIT_WINDOW_SECONDS", 60))
    now = time.monotonic()
    cutoff = now - window_seconds
    key = (scope, actor_key)

    with _LOCK:
        timestamps = [
            timestamp for timestamp in _REQUEST_TIMESTAMPS.get(key, []) if timestamp > cutoff
        ]
        if len(timestamps) >= max_requests:
            _REQUEST_TIMESTAMPS[key] = timestamps
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
            )
        timestamps.append(now)
        _REQUEST_TIMESTAMPS[key] = timestamps


def acquire_concurrency_limit(
    scope: str,
    actor_key: str,
    *,
    max_concurrent: int,
    detail: str = "Too many concurrent requests.",
) -> None:
    if not _enabled():
        return

    max_concurrent = max(1, max_concurrent)
    key = (scope, actor_key)
    with _LOCK:
        current = _IN_FLIGHT.get(key, 0)
        if current >= max_concurrent:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)
        _IN_FLIGHT[key] = current + 1


def release_concurrency_limit(scope: str, actor_key: str) -> None:
    if not _enabled():
        return

    key = (scope, actor_key)
    with _LOCK:
        current = _IN_FLIGHT.get(key, 0)
        if current <= 1:
            _IN_FLIGHT.pop(key, None)
        else:
            _IN_FLIGHT[key] = current - 1


def reset_rate_limits() -> None:
    with _LOCK:
        _REQUEST_TIMESTAMPS.clear()
        _IN_FLIGHT.clear()
