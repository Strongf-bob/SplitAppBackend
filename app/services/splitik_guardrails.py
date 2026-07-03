import re

_HOMEWORK_MARKERS = (
    "домашк",
    "дз",
    "задачу по",
    "реши задачу",
    "алгебр",
    "геометр",
    "контрольн",
)
_SECRET_REQUEST_MARKERS = (
    "дай пароль",
    "дай токен",
    "какой пароль",
    "какой токен",
    "покажи пароль",
    "покажи токен",
    "api key",
    "password",
    "private key",
    "секрет",
)
_FRIEND_PRIVATE_MARKERS = (
    "куда тратит",
    "на что тратит",
    "траты друга",
)


def _contains_any(message: str, markers: tuple[str, ...]) -> bool:
    lowered = message.casefold()
    return any(marker in lowered for marker in markers)


def _decision(allowed: bool, reason: str, message: str = "") -> dict:
    return {"allowed": allowed, "reason": reason, "message": message}


def sanitize_message(message: str) -> str:
    sanitized = re.sub(
        r"Authorization:\s*Bearer\s+\S+",
        "Authorization: Bearer [REDACTED]",
        message,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"token\s*=\s*\S+", "token=[REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(
        r"(api[_ -]?key|password|пароль)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def evaluate_user_message(message: str, *, context_scope: str = "general") -> dict:
    if _contains_any(message, _HOMEWORK_MARKERS):
        return _decision(
            False,
            "out_of_scope_homework",
            "Я могу помогать только со SplitApp: событиями, чеками, долгами и личными тратами.",
        )
    if _contains_any(message, _SECRET_REQUEST_MARKERS):
        return _decision(
            False,
            "secret_request",
            "Не отправляйте пароли, токены, ключи или платежные секреты в чат.",
        )
    if context_scope == "general" and _contains_any(message, _FRIEND_PRIVATE_MARKERS):
        return _decision(
            False,
            "private_friend_spending",
            "Я не могу раскрывать личные траты другого пользователя вне общего события.",
        )
    return _decision(True, "allowed")


def evaluate_structured_response(response: dict, *, capabilities: list[str]) -> dict:
    operation = str(response.get("operation") or response.get("tool") or "")
    forbidden = operation.startswith("forbidden:") or operation in {
        "delete_event",
        "edit_existing_money_state",
        "impersonate_user",
        "mark_foreign_payment_paid",
    }
    if forbidden:
        return _decision(
            False,
            "forbidden_operation",
            "Это действие заблокировано политикой безопасности SplitApp.",
        )
    return _decision(True, "allowed")
