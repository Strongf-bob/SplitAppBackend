from .auth import router as auth_router
from .events import router as events_router
from .health import router as health_router
from .payments import router as payments_router
from .receipts import router as receipts_router
from .users import router as users_router

__all__ = [
    "auth_router",
    "events_router",
    "health_router",
    "payments_router",
    "receipts_router",
    "users_router",
]
