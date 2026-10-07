"""Waitlist query selectors."""

import datetime
from dataclasses import dataclass

from django.db.models import Q

from agenda.constants import AppointmentStatus
from agenda.models import Appointment


@dataclass(frozen=True)
class WaitlistEntry:
    """Entry in the waitlist with calculated queue position."""

    appointment: Appointment
    position: int


def list_waitlist(target_date: datetime.date) -> list[WaitlistEntry]:
    """Return FIFO ordered list of waitlisted appointments for a given date with positions."""
    appointments = (
        Appointment.objects.filter(
            date=target_date,
            status=AppointmentStatus.WAITLISTED,
        )
        .select_related("requester", "service")
        .order_by("created_at", "id")
    )

    return [
        WaitlistEntry(appointment=appt, position=idx + 1) for idx, appt in enumerate(appointments)
    ]


def waitlist_position(appointment: Appointment) -> int | None:
    """Return 1-based FIFO position on its date, or None if not waitlisted."""
    if appointment.status != AppointmentStatus.WAITLISTED:
        return None

    preceding_count = (
        Appointment.objects.filter(
            date=appointment.date,
            status=AppointmentStatus.WAITLISTED,
        )
        .filter(
            Q(created_at__lt=appointment.created_at)
            | Q(created_at=appointment.created_at, id__lt=appointment.id)
        )
        .count()
    )

    return preceding_count + 1


def dates_with_waitlist(from_date: datetime.date) -> list[datetime.date]:
    """Return distinct dates with pending waitlisted appointments starting from from_date."""
    return list(
        Appointment.objects.filter(
            status=AppointmentStatus.WAITLISTED,
            date__gte=from_date,
        )
        .values_list("date", flat=True)
        .distinct()
        .order_by("date")
    )
