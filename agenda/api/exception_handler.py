"""Custom exception handler for Django REST Framework."""

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework_simplejwt.exceptions import (
    AuthenticationFailed as JWTAuthenticationFailed,
)
from rest_framework_simplejwt.exceptions import (
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

    if isinstance(exc, exceptions.Throttled):
        wait = int(exc.wait) if exc.wait is not None else 60
        response = Response(
            {
                "code": "THROTTLED",
                "detail": f"Límite de solicitudes excedido. Intente de nuevo en {wait} segundos.",
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(wait)
        return response

    if isinstance(exc, exceptions.ValidationError):
        detail_msg = "Parámetros de solicitud inválidos."
        if isinstance(exc.detail, str):
            detail_msg = exc.detail
        elif isinstance(exc.detail, list) and exc.detail:
            detail_msg = str(exc.detail[0])

        return Response(
            {
                "code": "INVALID_PARAMETERS",
                "detail": detail_msg,
                "errors": (
                    exc.detail if isinstance(exc.detail, (dict, list)) else {"detail": exc.detail}
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
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
