from .audit import router as audit_router
from .avatars import router as avatars_router
from .auth import router as auth_router
from .client_reports import router as client_reports_router
from .disputes import router as disputes_router
from .events import router as events_router
from .friends import router as friends_router
from .health import router as health_router
from .home import router as home_router
from .payments import router as payments_router
from .receipts import router as receipts_router
from .reports import router as reports_router
from .splitik import router as splitik_router
from .users import router as users_router

__all__ = [
    "audit_router",
    "avatars_router",
    "auth_router",
    "client_reports_router",
    "disputes_router",
    "events_router",
    "friends_router",
    "health_router",
    "home_router",
    "payments_router",
    "receipts_router",
    "reports_router",
    "splitik_router",
    "users_router",
]
