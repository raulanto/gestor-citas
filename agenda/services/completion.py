"""Completion and no-show attendance recording services."""

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from agenda.constants import AppointmentStatus, EventNote
from agenda.exceptions import InvalidStateTransition
from agenda.models import Appointment
from agenda.services.locks import day_advisory_lock
from agenda.services.transitions import transition


def complete_appointment(
    appointment: Appointment,
    *,
    actor: AbstractBaseUser | None = None,
    now: datetime.datetime | None = None,
) -> Appointment:
    """Mark a confirmed appointment as successfully completed after its start time."""
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)

    with transaction.atomic(), day_advisory_lock(appointment.date):
        appointment = Appointment.objects.select_for_update().get(id=appointment.id)

        if appointment.status != AppointmentStatus.CONFIRMED:
            raise InvalidStateTransition(
                f"No se puede completar una cita en estado '{appointment.status}'."
            )

        appt_start_local = timezone.localtime(appointment.start_at, tz)
        if now_local < appt_start_local:
            raise InvalidStateTransition("No se puede completar una cita que aún no ha iniciado.")

        return transition(
            appointment,
            AppointmentStatus.COMPLETED,
            actor=actor,
            note=EventNote.COMPLETED,
        )


def mark_no_show(
    appointment: Appointment,
    *,
    actor: AbstractBaseUser | None = None,
    now: datetime.datetime | None = None,
) -> Appointment:
    """Mark a confirmed appointment as no-show after its start time."""
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)

    with transaction.atomic(), day_advisory_lock(appointment.date):
        appointment = Appointment.objects.select_for_update().get(id=appointment.id)

        if appointment.status != AppointmentStatus.CONFIRMED:
            raise InvalidStateTransition(
                f"No se puede marcar inasistencia para una cita en estado '{appointment.status}'."
            )

        appt_start_local = timezone.localtime(appointment.start_at, tz)
        if now_local < appt_start_local:
            raise InvalidStateTransition(
                "No se puede marcar inasistencia para una cita que aún no ha iniciado."
            )

        return transition(
            appointment,
            AppointmentStatus.NO_SHOW,
            actor=actor,
            note=EventNote.NO_SHOW,
        )
