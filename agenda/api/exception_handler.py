"""Custom exception handler for Django REST Framework."""

from rest_framework.response import Response
from rest_framework.views import exception_handler

from agenda.exceptions import DomainError


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """Translate domain exceptions into standardized JSON error responses.

    Format: {"code": "...", "detail": "..."} with exc.http_status.
    Delegates all other exceptions to DRF's default exception handler.
    """
    if isinstance(exc, DomainError):
        return Response(
            {
                "code": exc.code,
                "detail": exc.detail,
            },
            status=exc.http_status,
        )

    return exception_handler(exc, context)
