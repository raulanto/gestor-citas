"""Booking service orchestration for scheduling and assigning appointments."""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import models, transaction
from django.utils import timezone

from agenda.constants import (
    ACTIVE_STATUSES,
    OCCUPYING_STATUSES,
    QUOTA_STATUSES,
    AppointmentStatus,
)
from agenda.exceptions import (
    DayClosed,
    InvalidSlot,
    OutsideBookingWindow,
    QuotaExceeded,
    RequesterLimitReached,
    ScheduleConflict,
    ServiceNotFound,
    WaitlistFull,
)
from agenda.models import Appointment, AppointmentEvent, Requester, Service, Worker
from agenda.selectors.day_configs import resolve_day_config
from agenda.selectors.workers import list_available_workers_on
from agenda.services.assignment import pick_worker
from agenda.services.capacity import (
    Interval,
    effective_quota,
    personnel_capacity,
    work_segments,
)
from agenda.services.locks import day_advisory_lock



@dataclass(frozen=True)
class BookingResult:
    """Result of booking an appointment."""

    appointment: Appointment
    outcome: str  # AppointmentStatus.CONFIRMED or AppointmentStatus.WAITLISTED


def book_appointment(
    *,
    requester: Requester,
    service: Service,
    start_at: datetime.datetime,
    actor: AbstractBaseUser | None = None,
    now: datetime.datetime | None = None,
) -> BookingResult:
    """Book an appointment with worker assignment or place on the waitlist.

    Validates booking window, service status, day open status, slot grid alignment,
    shift coverage, daily quota, requester active limits, and schedule conflicts.
    Serializes execution per date using a PostgreSQL transaction advisory lock.
    """
    if not service.is_active:
        raise ServiceNotFound()

    if timezone.is_naive(start_at):
        raise InvalidSlot("La fecha y hora de inicio debe incluir información de zona horaria.")

    tz = ZoneInfo(settings.TIME_ZONE)
    start_at_local = timezone.localtime(start_at, tz)
    end_at_local = start_at_local + datetime.timedelta(minutes=service.duration_minutes)

    if start_at_local.date() != end_at_local.date():
        raise InvalidSlot("La cita debe iniciar y concluir en el mismo día.")

    target_date = start_at_local.date()

    with transaction.atomic(), day_advisory_lock(target_date):
        # 1. Booking window validation
        if now is None:
            now = timezone.now()
        now_local = timezone.localtime(now, tz)
        today = now_local.date()

        min_advance_hours = getattr(settings, "BOOKING_MIN_ADVANCE_HOURS", 2)
        min_advance_dt = now_local + datetime.timedelta(hours=min_advance_hours)
        max_advance_days = getattr(settings, "BOOKING_MAX_ADVANCE_DAYS", 60)
        max_date = today + datetime.timedelta(days=max_advance_days)

        if target_date < today or start_at_local < min_advance_dt or target_date > max_date:
            raise OutsideBookingWindow()

        # 2. Day closed validation
        day_config = resolve_day_config(target_date)
        if not day_config.is_open:
            raise DayClosed()

        # 3. Slot grid alignment
        step_minutes = getattr(settings, "DEFAULT_SLOT_STEP_MINUTES", 15)
        if (
            start_at_local.minute % step_minutes != 0
            or start_at_local.second != 0
            or start_at_local.microsecond != 0
        ):
            raise InvalidSlot()

        # 4. Working shift coverage
        available_workers = list_available_workers_on(target_date)
        slot_interval = Interval(start_at_local.time(), end_at_local.time())

        candidate_workers: list[Worker] = []
        for worker, shift in available_workers:
            segments = work_segments(shift)
            if any(slot_interval.is_subset_of(seg) for seg in segments):
                candidate_workers.append(worker)

        if not candidate_workers:
            raise InvalidSlot()

        # 5. Daily quota validation
        shifts = [shift for _, shift in available_workers]
        staff_capacity = personnel_capacity(shifts, service.duration_minutes)
        eff_quota = effective_quota(day_config.max_appointments, staff_capacity)

        current_quota_count = Appointment.objects.filter(
            date=target_date,
            status__in=QUOTA_STATUSES,
        ).count()

        if eff_quota - current_quota_count <= 0:
            raise QuotaExceeded()

        # 6. Requester limits & conflict validation
        max_active_per_day = getattr(settings, "MAX_ACTIVE_PER_REQUESTER_PER_DAY", 1)
        requester_active = Appointment.objects.filter(
            requester=requester,
            date=target_date,
            status__in=ACTIVE_STATUSES,
        )

        if requester_active.count() >= max_active_per_day:
            raise RequesterLimitReached()

        for active_appt in requester_active:
            if active_appt.start_at < end_at_local and start_at_local < active_appt.end_at:
                raise ScheduleConflict()

        # 7. Worker assignment
        occupying_appts = Appointment.objects.filter(
            date=target_date,
            status__in=OCCUPYING_STATUSES,
            worker__in=candidate_workers,
        )

        busy_map: dict[int, list[Interval]] = {}
        for appt in occupying_appts:
            appt_start = timezone.localtime(appt.start_at, tz).time()
            appt_end = timezone.localtime(appt.end_at, tz).time()
            busy_map.setdefault(appt.worker_id, []).append(Interval(appt_start, appt_end))

        daily_loads: dict[int, int] = {}
        loads_qs = (
            Appointment.objects.filter(
                date=target_date,
                status__in=OCCUPYING_STATUSES,
                worker__in=candidate_workers,
            )
            .values("worker_id")
            .annotate(total=models.Count("id"))
        )
        for row in loads_qs:
            daily_loads[row["worker_id"]] = row["total"]

        assigned_worker = pick_worker(
            candidates=candidate_workers,
            slot_interval=slot_interval,
            busy_map=busy_map,
            daily_loads=daily_loads,
        )

        if assigned_worker is not None:
            appointment = Appointment.objects.create(
                requester=requester,
                service=service,
                worker=assigned_worker,
                date=target_date,
                start_at=start_at_local,
                end_at=end_at_local,
                status=AppointmentStatus.CONFIRMED,
            )
            AppointmentEvent.objects.create(
                appointment=appointment,
                from_status="",
                to_status=AppointmentStatus.CONFIRMED,
                worker=assigned_worker,
                actor=actor,
                note="Cita reservada y confirmada.",
            )
            return BookingResult(
                appointment=appointment,
                outcome=AppointmentStatus.CONFIRMED,
            )

        # 8. No free worker -> Waitlist
        waitlist_max = getattr(settings, "WAITLIST_MAX_PER_DAY", 20)
        current_waitlisted = Appointment.objects.filter(
            date=target_date,
            status=AppointmentStatus.WAITLISTED,
        ).count()

        if current_waitlisted >= waitlist_max:
            raise WaitlistFull()

        appointment = Appointment.objects.create(
            requester=requester,
            service=service,
            worker=None,
            date=target_date,
            start_at=start_at_local,
            end_at=end_at_local,
            status=AppointmentStatus.WAITLISTED,
        )
        AppointmentEvent.objects.create(
            appointment=appointment,
            from_status="",
            to_status=AppointmentStatus.WAITLISTED,
            worker=None,
            actor=actor,
            note="Cita colocada en lista de espera.",
        )
        return BookingResult(
            appointment=appointment,
            outcome=AppointmentStatus.WAITLISTED,
        )
