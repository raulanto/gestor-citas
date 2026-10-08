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
    http_status = 409


class QuotaExceeded(DomainError):
    """Raised when the daily appointment quota has been reached."""

    code = "quota_exceeded"
    detail = "Se ha superado el cupo de citas disponible para esta fecha."
    http_status = 409


class NoWorkerAvailable(DomainError):
    """Raised when no worker is available to take an appointment in the requested slot."""

    code = "no_worker_available"
    detail = "No hay personal disponible para el horario solicitado."
    http_status = 409


class CancellationNotAllowed(DomainError):
    """Raised when cancelling an appointment is not allowed due to advance notice rules."""

    code = "cancellation_not_allowed"
    detail = "No es posible cancelar la cita con el tiempo de anticipación actual."
    http_status = 409


class RescheduleLimitReached(DomainError):
    """Raised when the maximum number of reschedules has been reached for an appointment."""

    code = "reschedule_limit_reached"
    detail = "Se ha alcanzado el límite máximo de reprogramaciones para esta cita."
    http_status = 409


class InvalidStateTransition(DomainError):
    """Raised when an invalid appointment status transition is attempted."""

    code = "invalid_state_transition"
    detail = "La transición de estado solicitada no es válida para la cita."
    http_status = 409


class InvalidDuration(DomainError):
    """Raised when a service duration is outside the valid range (5-60 minutes)."""

    code = "invalid_duration"
    detail = "La duración del servicio es inválida (debe ser entre 5 y 60 minutos)."
    http_status = 400


class ScheduleConflict(DomainError):
    """Raised when an appointment schedule overlaps or conflicts with another booking."""

    code = "schedule_conflict"
    detail = "Existe un conflicto de horario con otra cita existente."
    http_status = 409


class InvalidSlot(DomainError):
    """Raised when the requested appointment slot does not match the grid or worker schedule."""

    code = "invalid_slot"
    detail = "El horario seleccionado no es válido."
    http_status = 400


class OutsideBookingWindow(DomainError):
    """Raised when attempting to book outside the allowed advance booking window."""

    code = "outside_booking_window"
    detail = "La fecha y hora solicitadas están fuera de la ventana permitida de reservas."
    http_status = 400


class RequesterLimitReached(DomainError):
    """Raised when a requester reaches the maximum allowed active appointments for a single day."""

    code = "requester_limit_reached"
    detail = "El solicitante ha alcanzado el límite de citas activas permitidas para esta fecha."
    http_status = 409


class WaitlistFull(DomainError):
    """Raised when the daily waitlist capacity has been exceeded."""

    code = "waitlist_full"
    detail = "La lista de espera para esta fecha ha alcanzado su capacidad máxima."
    http_status = 409


class AppointmentNotFound(DomainError):
    """Raised when a requested appointment does not exist."""

    code = "appointment_not_found"
    detail = "La cita solicitada no existe."
    http_status = 404


class ServiceNotFound(DomainError):
    """Raised when a requested service does not exist or is inactive."""

    code = "service_not_found"
    detail = "El servicio solicitado no existe o se encuentra inactivo."
    http_status = 404


class WorkerNotFound(DomainError):
    """Raised when a requested worker does not exist."""

    code = "worker_not_found"
    detail = "El trabajador solicitado no existe."
    http_status = 404


class ScheduleChangeNeedsConfirmation(DomainError):
    """Raised when a schedule change impacts existing appointments and requires explicit confirmation."""

    code = "SCHEDULE_CHANGE_REQUIRES_CONFIRMATION"
    detail = "El cambio de horario afecta citas existentes y requiere confirmación."
    http_status = 409

    def __init__(
        self,
        impact: dict | None = None,
        detail: str | None = None,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.impact = impact if impact is not None else {}
        super().__init__(detail=detail, code=code, http_status=http_status)
