"""Domain constants for agenda application."""

from django.db import models

MIN_SERVICE_DURATION_MINUTES = 5
MAX_SERVICE_DURATION_MINUTES = 60


class AppointmentStatus(models.TextChoices):
    """Lifecycle statuses for an appointment."""

    REQUESTED = "REQUESTED", "Solicitada"
    CONFIRMED = "CONFIRMED", "Confirmada"
    WAITLISTED = "WAITLISTED", "En espera"
    CANCELLED = "CANCELLED", "Cancelada"
    COMPLETED = "COMPLETED", "Completada"
    NO_SHOW = "NO_SHOW", "No presentado"
    RESCHEDULED = "RESCHEDULED", "Reprogramada"
    EXPIRED = "EXPIRED", "Expirada"


# Statuses that count against the daily quota
QUOTA_STATUSES = frozenset(
    {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.WAITLISTED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    }
)

# Statuses that occupy a worker's schedule/time
OCCUPYING_STATUSES = frozenset(
    {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    }
)

# Active statuses for checking requester daily limits and overlaps
ACTIVE_STATUSES = frozenset(
    {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.WAITLISTED,
    }
)

# Inactive statuses that do not consume quota or occupy time
NON_QUOTA_STATUSES = frozenset(
    {
        AppointmentStatus.CANCELLED,
        AppointmentStatus.RESCHEDULED,
        AppointmentStatus.EXPIRED,
    }
)


class EventNote:
    """Standard note messages for appointment audit events."""

    BOOKED_CONFIRMED = "Cita reservada y confirmada."
    BOOKED_WAITLISTED = "Cita en lista de espera por falta de personal disponible."
    WAITLIST_ASSIGNED = "Asignada desde lista de espera"
    WAITLIST_EXPIRED = "Expirada sin asignación"
