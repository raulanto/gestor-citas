"""Selectors for worker schedules, day configuration summaries, and unserviceable waitlist."""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from agenda.constants import ACTIVE_STATUSES, QUOTA_STATUSES, AppointmentStatus
from agenda.models import Appointment, DayConfig, ScheduleException, Service, Worker, WorkSchedule
from agenda.selectors.day_configs import resolve_day_config
from agenda.selectors.workers import list_available_workers_on
from agenda.services.capacity import Interval, effective_quota, personnel_capacity, work_segments


@dataclass(frozen=True)
class DayConfigSummary:
    """Summary of day configuration and capacity metrics for a given date."""

    date: datetime.date
    day_config: DayConfig
    is_open: bool
    effective_quota: int | None
    quota_consumed: int
    active_count: int
    is_over_quota: bool


def get_worker_schedule(worker: Worker) -> dict:
    """Retrieve complete weekly schedule and upcoming date exceptions for a worker."""
    tz = ZoneInfo(settings.TIME_ZONE)
    today = timezone.localdate(timezone.now(), tz)

    weekly_schedules = list(WorkSchedule.objects.filter(worker=worker).order_by("weekday"))
    upcoming_exceptions = list(
        ScheduleException.objects.filter(worker=worker, date__gte=today).order_by("date")
    )

    return {
        "worker": worker,
        "weekly_schedules": weekly_schedules,
        "exceptions": upcoming_exceptions,
    }


def get_day_config_summary(target_date: datetime.date) -> DayConfigSummary:
    """Calculate day configuration summary, effective quota, and quota status."""
    day_config = resolve_day_config(target_date)
    min_service = Service.objects.filter(is_active=True).order_by("duration_minutes").first()

    available_workers = list_available_workers_on(target_date) if day_config.is_open else []

    if day_config.is_open and min_service is not None:
        shifts = [shift for _, shift in available_workers]
        cap = personnel_capacity(shifts, min_service.duration_minutes)
        eff_quota = effective_quota(day_config.max_appointments, cap)
    elif not day_config.is_open:
        eff_quota = 0
    else:
        eff_quota = day_config.max_appointments

    quota_consumed = Appointment.objects.filter(date=target_date, status__in=QUOTA_STATUSES).count()
    active_count = Appointment.objects.filter(date=target_date, status__in=ACTIVE_STATUSES).count()

    is_over = eff_quota is not None and quota_consumed > eff_quota

    return DayConfigSummary(
        date=target_date,
        day_config=day_config,
        is_open=day_config.is_open,
        effective_quota=eff_quota,
        quota_consumed=quota_consumed,
        active_count=active_count,
        is_over_quota=is_over,
    )


def list_unserviceable_waitlist(
    from_date: datetime.date | None = None,
    now: datetime.datetime | None = None,
) -> list[Appointment]:
    """Find all future waitlisted appointments whose slot cannot be served by any worker."""
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)
    today = now_local.date()

    start_date = from_date if from_date is not None else today

    waitlisted_appts = (
        Appointment.objects.filter(
            status=AppointmentStatus.WAITLISTED,
            date__gte=start_date,
            start_at__gt=now_local,
        )
        .select_related("requester", "service", "worker")
        .order_by("date", "created_at", "id")
    )

    unserviceable: list[Appointment] = []
    # Cache shifts by date
    shift_cache: dict[datetime.date, list[Interval]] = {}

    for appt in waitlisted_appts:
        appt_date = appt.date
        if appt_date not in shift_cache:
            workers_with_shifts = list_available_workers_on(appt_date)
            segments: list[Interval] = []
            for _, shift in workers_with_shifts:
                segments.extend(work_segments(shift))
            shift_cache[appt_date] = segments

        segments_for_date = shift_cache[appt_date]
        slot_start = timezone.localtime(appt.start_at, tz).time()
        slot_end = timezone.localtime(appt.end_at, tz).time()
        slot_interval = Interval(slot_start, slot_end)

        if not any(slot_interval.is_subset_of(seg) for seg in segments_for_date):
            unserviceable.append(appt)

    return unserviceable
