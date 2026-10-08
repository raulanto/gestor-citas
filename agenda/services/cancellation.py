"""Cancellation and rescheduling services for appointment lifecycle management."""

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from agenda.constants import ACTIVE_STATUSES, AppointmentStatus, EventNote
from agenda.exceptions import (
    CancellationNotAllowed,
    InvalidSlot,
    InvalidStateTransition,
    RescheduleLimitReached,
)
from agenda.logging import log_event
from agenda.models import Appointment
from agenda.services.booking import BookingResult, create_appointment_in_lock

from agenda.services.locks import day_advisory_lock, day_advisory_locks
from agenda.services.transitions import transition
from agenda.services.waitlist import process_waitlist


def cancel_appointment(
    appointment: Appointment,
    *,
    reason: str = "",
    actor: AbstractBaseUser | None = None,
    force: bool = False,
    now: datetime.datetime | None = None,
) -> Appointment:
    """Cancel an appointment respecting advance notice rules, releasing capacity.

    Triggers waitlist processing on the same date.
    If force is True (staff only), advance notice rules are bypassed.
    If the appointment is already CANCELLED, returns success idempotently without extra events.
    """
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)

    with transaction.atomic(), day_advisory_lock(appointment.date):
        appointment = Appointment.objects.select_for_update().get(id=appointment.id)

        # Idempotency: cancelling an already CANCELLED appointment is a no-op
        if appointment.status == AppointmentStatus.CANCELLED:
            return appointment

        # Terminal state check
        if appointment.status in (
            AppointmentStatus.EXPIRED,
            AppointmentStatus.RESCHEDULED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
        ):
            raise InvalidStateTransition(
                f"No se puede cancelar una cita en estado terminal '{appointment.status}'."
            )

        appt_start_local = timezone.localtime(appointment.start_at, tz)

        # Timing check: past or started appointments cannot be cancelled even with force
        if appt_start_local <= now_local:
            raise CancellationNotAllowed(
                "No se puede cancelar una cita que ya ha iniciado o pasado."
            )

        # Advance notice validation
        if not force:
            if appointment.status == AppointmentStatus.CONFIRMED:
                min_hours = getattr(settings, "CANCEL_MIN_HOURS", 4)
                cancel_limit = appt_start_local - datetime.timedelta(hours=min_hours)
                if now_local > cancel_limit:
                    raise CancellationNotAllowed(
                        "No es posible cancelar la cita con el tiempo de anticipación actual."
                    )

        was_confirmed = appointment.status == AppointmentStatus.CONFIRMED

        note = reason.strip() if reason else EventNote.CANCELLED
        if force:
            note = f"{note} (Forzada por staff)" if note else "Cita cancelada. (Forzada por staff)"

        transition(
            appointment,
            AppointmentStatus.CANCELLED,
            actor=actor,
            note=note,
        )

        if was_confirmed:
            process_waitlist(appointment.date, now=now)

        log_event("appointment_cancelled", appointment_id=str(appointment.id))
        return appointment



def reschedule_appointment(
    appointment: Appointment,
    new_start_at: datetime.datetime,
    *,
    actor: AbstractBaseUser | None = None,
    force: bool = False,
    allow_waitlist: bool = False,
    now: datetime.datetime | None = None,
) -> BookingResult:
    """Reschedule an existing appointment to a new date and time atomically.

    Validates advance notice and maximum reschedules, transitions original appointment
    to RESCHEDULED, and creates the new booking. Reverts completely if booking fails.
    """
    if timezone.is_naive(new_start_at):
        raise InvalidSlot("La fecha y hora de inicio debe incluir información de zona horaria.")

    tz = ZoneInfo(settings.TIME_ZONE)
    new_start_at_local = timezone.localtime(new_start_at, tz)
    new_date = new_start_at_local.date()
    orig_date = appointment.date

    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)

    # Acquire advisory locks in ascending order to prevent deadlocks across days
    with transaction.atomic(), day_advisory_locks(orig_date, new_date):
        appointment = Appointment.objects.select_for_update().get(id=appointment.id)

        if appointment.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.WAITLISTED):
            raise InvalidStateTransition(
                f"No se puede reprogramar una cita en estado '{appointment.status}'."
            )

        appt_start_local = timezone.localtime(appointment.start_at, tz)

        # Timing check: past or started appointments cannot be rescheduled even with force
        if appt_start_local <= now_local:
            raise CancellationNotAllowed(
                "No se puede reprogramar una cita que ya ha iniciado o pasado."
            )

        # Advance notice and reschedule count validation
        if not force:
            if appointment.status == AppointmentStatus.CONFIRMED:
                min_hours = getattr(settings, "CANCEL_MIN_HOURS", 4)
                cancel_limit = appt_start_local - datetime.timedelta(hours=min_hours)
                if now_local > cancel_limit:
                    raise CancellationNotAllowed(
                        "No es posible reprogramar la cita con el tiempo de anticipación actual."
                    )

            max_reschedules = getattr(settings, "MAX_RESCHEDULES_PER_APPOINTMENT", 2)
            if appointment.reschedule_count >= max_reschedules:
                raise RescheduleLimitReached()

        # Slot uniqueness check: new slot must be different from current slot
        if new_start_at_local == appt_start_local:
            raise InvalidSlot("La nueva fecha y hora debe ser diferente a la actual.")

        was_confirmed = appointment.status == AppointmentStatus.CONFIRMED

        # Decision 6: CONFIRMED appointments only degrade to WAITLISTED if explicitly requested
        effective_allow_waitlist = allow_waitlist if was_confirmed else True

        # Transition original appointment to RESCHEDULED to free capacity & requester limits
        transition(
            appointment,
            AppointmentStatus.RESCHEDULED,
            actor=actor,
            note=EventNote.RESCHEDULED,
        )

        # Create new appointment using booking core
        new_result = create_appointment_in_lock(
            requester=appointment.requester,
            service=appointment.service,
            start_at=new_start_at_local,
            actor=actor,
            now=now,
            rescheduled_from=appointment,
            reschedule_count=appointment.reschedule_count + 1,
            allow_waitlist=effective_allow_waitlist,
        )

        # Reevaluate waitlist on original date if a worker was freed
        if was_confirmed:
            process_waitlist(orig_date, now=now)

        log_event(
            "appointment_rescheduled",
            old_appointment_id=str(appointment.id),
            new_appointment_id=str(new_result.appointment.id),
        )
        return new_result



def cancel_appointments_for_day(
    target_date: datetime.date,
    *,
    reason: str = "Cancelación masiva por cierre del día.",
    actor: AbstractBaseUser | None = None,
    now: datetime.datetime | None = None,
) -> int:
    """Cancel all active future appointments for a specific date (Staff only)."""
    if now is None:
        now = timezone.now()

    with transaction.atomic(), day_advisory_lock(target_date):
        active_appts = list(
            Appointment.objects.filter(
                date=target_date,
                status__in=ACTIVE_STATUSES,
                start_at__gt=now,
            ).select_for_update()
        )

        count = 0
        for appt in active_appts:
            cancel_appointment(
                appt,
                reason=reason,
                actor=actor,
                force=True,
                now=now,
            )
            count += 1

        return count
