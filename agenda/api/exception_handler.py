"""Custom exception handler for Django REST Framework."""

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework_simplejwt.exceptions import (
    AuthenticationFailed as JWTAuthenticationFailed,
    InvalidToken,
)

from agenda.exceptions import DomainError


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """Translate domain, authentication, and permission exceptions into standardized JSON responses.

    Format: {"code": "...", "detail": "..."} with appropriate HTTP status.
    """
    if isinstance(exc, DomainError):
        data = {
            "code": exc.code,
            "detail": exc.detail,
        }
        if hasattr(exc, "impact") and exc.impact is not None:
            data["impact"] = exc.impact
        return Response(
            data,
            status=exc.http_status,
        )

    if isinstance(exc, exceptions.NotAuthenticated):
        return Response(
            {
                "code": "NOT_AUTHENTICATED",
                "detail": "Las credenciales de autenticación no fueron provistas.",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, (InvalidToken, JWTAuthenticationFailed, exceptions.AuthenticationFailed)):
        return Response(
            {
                "code": "INVALID_TOKEN",
                "detail": "Token inválido o expirado.",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, exceptions.PermissionDenied):
        return Response(
            {
                "code": "FORBIDDEN",
                "detail": "No tiene permiso para realizar esta acción.",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, (Http404, exceptions.NotFound)):
        return Response(
            {
                "code": "APPOINTMENT_NOT_FOUND",
                "detail": "El recurso solicitado no fue encontrado.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    return exception_handler(exc, context)
