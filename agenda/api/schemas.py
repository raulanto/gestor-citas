"""OpenAPI schema helper serializers and error codes for drf-spectacular."""

from enum import StrEnum

from rest_framework import serializers


class ApiErrorCode(StrEnum):
    """Enumeration of all error codes returned by the API."""

    # Domain Errors
    DAY_CLOSED = "DAY_CLOSED"
    SERVICE_NOT_FOUND = "SERVICE_NOT_FOUND"
    INVALID_TIME_SLOT = "INVALID_TIME_SLOT"
    SLOT_OUTSIDE_SHIFT = "SLOT_OUTSIDE_SHIFT"
    SLOT_OVERLAPS_BREAK = "SLOT_OVERLAPS_BREAK"
    ADVANCE_TOO_SHORT = "ADVANCE_TOO_SHORT"
    ADVANCE_TOO_FAR = "ADVANCE_TOO_FAR"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    REQUESTER_DAILY_LIMIT = "REQUESTER_DAILY_LIMIT"
    REQUESTER_OVERLAPPING_SLOT = "REQUESTER_OVERLAPPING_SLOT"
    WAITLIST_FULL = "WAITLIST_FULL"
    CANCELLATION_TOO_LATE = "CANCELLATION_TOO_LATE"
    RESCHEDULE_LIMIT_REACHED = "RESCHEDULE_LIMIT_REACHED"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    SCHEDULE_CHANGE_REQUIRES_CONFIRMATION = "SCHEDULE_CHANGE_REQUIRES_CONFIRMATION"
    WORKER_ALREADY_EXISTS = "WORKER_ALREADY_EXISTS"
    INVALID_SCHEDULE_ENTRY = "INVALID_SCHEDULE_ENTRY"
    SCHEDULE_EXCEPTION_COLLISION = "SCHEDULE_EXCEPTION_COLLISION"

    # Authentication & Authorization Errors
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    INVALID_TOKEN = "INVALID_TOKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    LOGIN_LOCKED = "LOGIN_LOCKED"
    FORBIDDEN = "FORBIDDEN"

    # Operational & Input Errors
    THROTTLED = "THROTTLED"
    APPOINTMENT_NOT_FOUND = "APPOINTMENT_NOT_FOUND"
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
