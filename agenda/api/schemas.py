"""OpenAPI schema helper serializers and error codes for drf-spectacular."""

from enum import StrEnum

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import serializers


class ApiErrorCode(StrEnum):
    """Enumeration of all error codes returned by the API."""

    # Domain Errors
    DOMAIN_ERROR = "domain_error"
    DAY_CLOSED = "day_closed"
    QUOTA_EXCEEDED = "quota_exceeded"
    NO_WORKER_AVAILABLE = "no_worker_available"
    CANCELLATION_NOT_ALLOWED = "cancellation_not_allowed"
    RESCHEDULE_LIMIT_REACHED = "reschedule_limit_reached"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    INVALID_DURATION = "invalid_duration"
    SCHEDULE_CONFLICT = "schedule_conflict"
    INVALID_SLOT = "invalid_slot"
    OUTSIDE_BOOKING_WINDOW = "outside_booking_window"
    REQUESTER_LIMIT_REACHED = "requester_limit_reached"
    WAITLIST_FULL = "waitlist_full"
    APPOINTMENT_NOT_FOUND_DOMAIN = "appointment_not_found"
    SERVICE_NOT_FOUND = "service_not_found"
    WORKER_NOT_FOUND = "worker_not_found"
    SCHEDULE_CHANGE_REQUIRES_CONFIRMATION = "SCHEDULE_CHANGE_REQUIRES_CONFIRMATION"

    # Authentication & Authorization Errors
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    INVALID_TOKEN = "INVALID_TOKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    LOGIN_LOCKED = "LOGIN_LOCKED"
    FORBIDDEN = "FORBIDDEN"

    # Operational & Input Errors
    THROTTLED = "THROTTLED"
    APPOINTMENT_NOT_FOUND = "APPOINTMENT_NOT_FOUND"
    EXCEPTION_NOT_FOUND = "EXCEPTION_NOT_FOUND"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class ErrorResponseSerializer(serializers.Serializer):
    """Standardized error response payload."""

    code = serializers.ChoiceField(
        choices=[code.value for code in ApiErrorCode],
        help_text="Código único de error de dominio u operación.",
    )
    detail = serializers.CharField(help_text="Mensaje explicativo para el usuario.")
    impact = serializers.DictField(
        required=False,
        help_text="Desglose del impacto de cambios de horario cuando se requiere confirmación.",
    )
    errors = serializers.DictField(
        required=False,
        help_text="Detalles de validación de campos específicos si aplica.",
    )


class HealthReadyResponseSerializer(serializers.Serializer):
    """Health check readiness response payload."""

    status = serializers.CharField(help_text="Estado del servicio ('ok' o 'unavailable').")
    failing = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Lista de componentes no disponibles (ej. 'database', 'cache').",
    )


class CustomJWTScheme(OpenApiAuthenticationExtension):
    target_class = "agenda.api.auth.authentication.CustomJWTAuthentication"
    name = "BearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
