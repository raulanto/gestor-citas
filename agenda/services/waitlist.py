"""Waitlist processing, promotion, and expiration service."""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from agenda.constants import OCCUPYING_STATUSES, AppointmentStatus, EventNote
from agenda.models import Appointment, AppointmentEvent, Worker
from agenda.selectors.day_configs import resolve_day_config
from agenda.selectors.waitlist import dates_with_waitlist
from agenda.selectors.workers import list_available_workers_on
from agenda.services.assignment import pick_worker
from agenda.services.capacity import Interval, work_segments
from agenda.services.locks import day_advisory_lock


@dataclass(frozen=True)
class WaitlistResult:
    """Result of processing the waitlist for a specific date."""

    assigned: list[Appointment]
    remaining: int


def process_waitlist(
    target_date: datetime.date,
    *,
    now: datetime.datetime | None = None,
) -> WaitlistResult:
    """Process waitlisted appointments for target_date in FIFO order without head-of-line blocking.

    Assigns available workers to eligible waitlisted appointments.
    Runs inside an atomic transaction taking the day advisory lock.
    """
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)
    today = now_local.date()

    if target_date < today:
        return WaitlistResult(assigned=[], remaining=0)

    with transaction.atomic(), day_advisory_lock(target_date):
        day_config = resolve_day_config(target_date)
        if not day_config.is_open:
            remaining = Appointment.objects.filter(
                date=target_date,
                status=AppointmentStatus.WAITLISTED,
            ).count()
            return WaitlistResult(assigned=[], remaining=remaining)

        # 1. Fetch active waitlisted appointments in FIFO order
        waitlisted_appts = list(
            Appointment.objects.filter(
                date=target_date,
                status=AppointmentStatus.WAITLISTED,
                start_at__gt=now_local,
            )
            .select_related("requester", "service")
            .order_by("created_at", "id")
        )

        if not waitlisted_appts:
            return WaitlistResult(assigned=[], remaining=0)

        # 2. Load workers and occupied intervals once into memory
        available_workers = list_available_workers_on(target_date)
        if not available_workers:
            return WaitlistResult(assigned=[], remaining=len(waitlisted_appts))

        candidate_worker_map = {worker.id: (worker, shift) for worker, shift in available_workers}

        occupying_appts = Appointment.objects.filter(
            date=target_date,
            status__in=OCCUPYING_STATUSES,
            worker__isnull=False,
        )

        busy_map: dict[int, list[Interval]] = {w.id: [] for w, _ in available_workers}
        daily_loads: dict[int, int] = {w.id: 0 for w, _ in available_workers}

        for appt in occupying_appts:
            if appt.worker_id in candidate_worker_map:
                appt_start = timezone.localtime(appt.start_at, tz).time()
                appt_end = timezone.localtime(appt.end_at, tz).time()
                busy_map[appt.worker_id].append(Interval(appt_start, appt_end))
                daily_loads[appt.worker_id] += 1

        # 3. Process each waitlisted appointment
        assigned_list: list[Appointment] = []

        for appt in waitlisted_appts:
            appt_start_t = timezone.localtime(appt.start_at, tz).time()
            appt_end_t = timezone.localtime(appt.end_at, tz).time()
            slot_interval = Interval(appt_start_t, appt_end_t)

            # Find workers whose shift covers the slot
            candidates: list[Worker] = []
            for worker, shift in available_workers:
                segments = work_segments(shift)
                if any(slot_interval.is_subset_of(seg) for seg in segments):
                    candidates.append(worker)

            if not candidates:
                # Slot cannot be served by current shifts; skip without blocking queue
                continue

            assigned_worker = pick_worker(
                candidates=candidates,
                slot_interval=slot_interval,
                busy_map=busy_map,
                daily_loads=daily_loads,
            )

            if assigned_worker is not None:
                # Promote waitlisted appointment to CONFIRMED
                appt.worker = assigned_worker
                appt.status = AppointmentStatus.CONFIRMED
                appt.save(update_fields=["worker", "status", "updated_at"])

                AppointmentEvent.objects.create(
                    appointment=appt,
                    from_status=AppointmentStatus.WAITLISTED,
                    to_status=AppointmentStatus.CONFIRMED,
                    worker=assigned_worker,
                    actor=None,
                    note=EventNote.WAITLIST_ASSIGNED,
                )

                # Update in-memory state
                busy_map[assigned_worker.id].append(slot_interval)
                daily_loads[assigned_worker.id] += 1
                assigned_list.append(appt)

        remaining_count = Appointment.objects.filter(
            date=target_date,
            status=AppointmentStatus.WAITLISTED,
        ).count()

        return WaitlistResult(assigned=assigned_list, remaining=remaining_count)


def process_waitlist_all(now: datetime.datetime | None = None) -> list[WaitlistResult]:
    """Process waitlist for all dates from today onwards with pending waitlisted appointments."""
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)
    today = now_local.date()

    target_dates = dates_with_waitlist(today)
    return [process_waitlist(target_date, now=now) for target_date in target_dates]


def expire_waitlist(now: datetime.datetime | None = None) -> int:
    """Mark EXPIRED all waitlisted appointments whose start_at has passed."""
    if now is None:
        now = timezone.now()

    expired_candidates = Appointment.objects.filter(
        status=AppointmentStatus.WAITLISTED,
        start_at__lte=now,
    )
    dates = list(expired_candidates.values_list("date", flat=True).distinct())

    total_expired = 0
    for target_date in dates:
        with transaction.atomic(), day_advisory_lock(target_date):
            appts_to_expire = list(
                Appointment.objects.filter(
                    date=target_date,
                    status=AppointmentStatus.WAITLISTED,
                    start_at__lte=now,
                )
            )
            for appt in appts_to_expire:
                appt.status = AppointmentStatus.EXPIRED
                appt.save(update_fields=["status", "updated_at"])

                AppointmentEvent.objects.create(
                    appointment=appt,
                    from_status=AppointmentStatus.WAITLISTED,
                    to_status=AppointmentStatus.EXPIRED,
                    worker=None,
                    actor=None,
                    note=EventNote.WAITLIST_EXPIRED,
                )
                total_expired += 1

    return total_expired


def schedule_waitlist_processing() -> None:
    """Schedule asynchronous waitlist processing on transaction commit."""
    if getattr(connection, "_waitlist_processing_scheduled", False):
        return

    connection._waitlist_processing_scheduled = True

    def _run() -> None:
        connection._waitlist_processing_scheduled = False
        from agenda.tasks import process_waitlist_all_task

        try:
            process_waitlist_all_task.delay()
        except Exception:
            process_waitlist_all()

    transaction.on_commit(_run)
