import datetime
import uuid

from django.db.models import QuerySet

from agenda.constants import ACTIVE_STATUSES
from agenda.exceptions import AppointmentNotFound
from agenda.models import Appointment


def get_appointment(appointment_id: uuid.UUID | str) -> Appointment:
    """Retrieve an appointment by its ID with related models preloaded.

    Raises AppointmentNotFound if no matching record exists.
    """
    try:
        if isinstance(appointment_id, str):
            appointment_id = uuid.UUID(appointment_id)
    except (ValueError, AttributeError):
        raise AppointmentNotFound() from None

    appointment = (
        Appointment.objects.select_related("requester", "service", "worker", "rescheduled_from")
        .prefetch_related("rescheduled_children")
        .filter(id=appointment_id)
        .first()
    )

    if appointment is None:
        raise AppointmentNotFound()

    return appointment


def list_active_appointments(target_date: datetime.date) -> list[Appointment]:
    """Retrieve all active appointments (CONFIRMED, WAITLISTED) for a given date."""
    return list(
        Appointment.objects.filter(
            date=target_date,
            status__in=ACTIVE_STATUSES,
        )
        .select_related("requester", "service", "worker")
        .order_by("start_at", "id")
    )


def list_appointments_queryset(
    target_date: datetime.date | None = None,
    status_filter: str | None = None,
) -> QuerySet[Appointment]:
    """Retrieve a queryset of appointments optionally filtered by date and status."""
    qs = (
        Appointment.objects.all()
        .select_related("requester", "service", "worker", "rescheduled_from")
        .prefetch_related("rescheduled_children")
        .order_by("-start_at", "-created_at")
    )

    if target_date is not None:
        qs = qs.filter(date=target_date)

    if status_filter:
        qs = qs.filter(status=status_filter)

    return qs
