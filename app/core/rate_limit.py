import os
import threading
import time

from fastapi import HTTPException, status

_LOCK = threading.Lock()
_REQUEST_TIMESTAMPS: dict[tuple[str, str], list[float]] = {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def check_rate_limit(scope: str, actor_key: str) -> None:
    if not _enabled():
        return

    max_requests = max(1, _env_int("RATE_LIMIT_MAX_REQUESTS", 60))
    window_seconds = max(1, _env_int("RATE_LIMIT_WINDOW_SECONDS", 60))
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
                detail="Too many requests.",
            )
        timestamps.append(now)
        _REQUEST_TIMESTAMPS[key] = timestamps


def reset_rate_limits() -> None:
    with _LOCK:
        _REQUEST_TIMESTAMPS.clear()
