"""Domain exceptions for the agenda application."""


class DomainError(Exception):
    """Base domain exception with error code, human-readable detail, and HTTP status code."""

    code: str = "domain_error"
    detail: str = "Ha ocurrido un error en la lógica de negocio."
    http_status: int = 400

    def __init__(
        self,
        detail: str | None = None,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        if detail is not None:
            self.detail = detail
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        super().__init__(self.detail)


class DayClosed(DomainError):
    """Raised when an operation is attempted on a closed date."""

    code = "day_closed"
    detail = "El día seleccionado se encuentra cerrado para citas."
    http_status = 400


class QuotaExceeded(DomainError):
    """Raised when the daily appointment quota has been reached."""

    code = "quota_exceeded"
    detail = "Se ha superado el cupo de citas disponible para esta fecha."
    http_status = 400


class NoWorkerAvailable(DomainError):
    """Raised when no worker is available to take an appointment in the requested slot."""

    code = "no_worker_available"
    detail = "No hay personal disponible para el horario solicitado."
    http_status = 400


class CancellationNotAllowed(DomainError):
    """Raised when cancelling an appointment is not allowed due to advance notice rules."""

    code = "cancellation_not_allowed"
    detail = "No es posible cancelar la cita con el tiempo de anticipación actual."
    http_status = 400


class RescheduleLimitReached(DomainError):
    """Raised when the maximum number of reschedules has been reached for an appointment."""

    code = "reschedule_limit_reached"
    detail = "Se ha alcanzado el límite máximo de reprogramaciones para esta cita."
    http_status = 400


class InvalidDuration(DomainError):
    """Raised when a service duration is outside the valid range (5-60 minutes)."""

    code = "invalid_duration"
    detail = "La duración del servicio es inválida (debe ser entre 5 y 60 minutos)."
    http_status = 400


class ScheduleConflict(DomainError):
    """Raised when an appointment schedule overlaps or conflicts with another booking."""

    code = "schedule_conflict"
    detail = "Existe un conflicto de horario con otra cita existente."
    http_status = 400


class AppointmentNotFound(DomainError):
    """Raised when a requested appointment does not exist."""

    code = "appointment_not_found"
    detail = "La cita solicitada no existe."
    http_status = 404


class ServiceNotFound(DomainError):
    """Raised when a requested service does not exist or is inactive."""

    code = "SERVICE_NOT_FOUND"
    detail = "El servicio solicitado no existe o se encuentra inactivo."
    http_status = 404
