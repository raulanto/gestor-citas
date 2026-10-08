"""Structured logging context and domain event logging."""

from contextvars import ContextVar
import logging
from typing import Any

# Context variables for request tracing
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_ctx_var: ContextVar[int | None] = ContextVar("user_id", default=None)
role_ctx_var: ContextVar[str] = ContextVar("role", default="ANONYMOUS")

FORBIDDEN_PII_KEYS = frozenset(
    {
        "phone",
        "email",
        "full_name",
        "manage_token",
        "password",
        "access",
        "refresh",
        "username",
        "token",
    }
)


def get_request_id() -> str:
    """Retrieve the current request ID from context."""
    return request_id_ctx_var.get() or ""


def log_event(name: str, **ids: Any) -> None:
    """Log a structured domain event.

    Rejects any keyword arguments that match forbidden PII field names.
    """
    for key in ids:
        if key.lower() in FORBIDDEN_PII_KEYS:
            raise ValueError(
                f"Forbidden PII key '{key}' in log_event. Personal data must never be logged."
            )

    logger = logging.getLogger("agenda.events")
    logger.info(
        f"Domain event: {name}",
        extra={
            "event": name,
            "request_id": get_request_id(),
            **ids,
        },
    )
