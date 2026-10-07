"""Appointment status transition service and state machine enforcement."""

from typing import Any

from agenda.constants import ALLOWED_TRANSITIONS, AppointmentStatus
from agenda.exceptions import InvalidStateTransition
from agenda.models import Appointment, AppointmentEvent, Worker

_UNSET = object()


def transition(
    appointment: Appointment,
    to_status: str | AppointmentStatus,
    *,
    actor: Any = None,
    note: str = "",
    worker: Worker | None | object = _UNSET,
) -> Appointment:
    """Validate and perform an appointment status transition, recording an audit event.

    This is the single entry point for changing appointment status.
    Raises InvalidStateTransition if the requested transition is not permitted.
    """
    from_status = appointment.status
    allowed = ALLOWED_TRANSITIONS.get(from_status, frozenset())

    if to_status not in allowed:
        raise InvalidStateTransition(
            f"No se permite la transición de estado desde {from_status} hacia {to_status}."
        )

    appointment.status = str(to_status)
    update_fields = ["status", "updated_at"]

    if worker is not _UNSET:
        appointment.worker = worker  # type: ignore[assignment]
        update_fields.append("worker")

    appointment.save(update_fields=update_fields)

    AppointmentEvent.objects.create(
        appointment=appointment,
        from_status=from_status,
        to_status=str(to_status),
        worker=appointment.worker,
        actor=actor,
        note=note,
    )

    return appointment
