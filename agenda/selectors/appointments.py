"""Appointment query selectors."""

import uuid

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
        Appointment.objects.select_related("requester", "service", "worker")
        .filter(id=appointment_id)
        .first()
    )

    if appointment is None:
        raise AppointmentNotFound()

    return appointment
