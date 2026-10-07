"""Availability selector for querying open slots and capacity for a service on a given date."""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from agenda.models import Service
from agenda.ports import BusySlotsPort, NullBusySlots
from agenda.selectors.day_configs import resolve_day_config
from agenda.selectors.workers import list_available_workers_on
from agenda.services.capacity import (
    effective_quota,
    generate_slots,
    personnel_capacity,
)


@dataclass(frozen=True)
class Slot:
    """Individual appointment time slot with available workers count."""

    start: datetime.datetime
    end: datetime.datetime
    free_workers: int


@dataclass(frozen=True)
class DayAvailability:
    """Full availability report for a service on a target date."""

    date: datetime.date
    is_open: bool
    effective_quota: int
    remaining_quota: int
    slots: list[Slot]
    reason: str | None


def get_day_availability(
    target_date: datetime.date,
    service: Service,
    *,
    busy: BusySlotsPort | None = None,
    now: datetime.datetime | None = None,
) -> DayAvailability:
    """Calculate availability and bookable slots for a service on a target date."""
    if busy is None:
        busy = NullBusySlots()

    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()

    current_local_dt = timezone.localtime(now, tz)
    today = current_local_dt.date()

    # 1. Booking window check (OUT_OF_WINDOW)
    max_advance_days = getattr(settings, "BOOKING_MAX_ADVANCE_DAYS", 60)
    max_date = today + datetime.timedelta(days=max_advance_days)

    if target_date < today or target_date > max_date:
        return DayAvailability(
            date=target_date,
            is_open=False,
            effective_quota=0,
            remaining_quota=0,
            slots=[],
            reason="OUT_OF_WINDOW",
        )

    # 2. Day configuration open/closed check (DAY_CLOSED)
    day_config = resolve_day_config(target_date)
    if not day_config.is_open:
        return DayAvailability(
            date=target_date,
            is_open=False,
            effective_quota=0,
            remaining_quota=0,
            slots=[],
            reason="DAY_CLOSED",
        )

    # 3. Personnel capacity check (NO_STAFF)
    available_workers = list_available_workers_on(target_date)
    shifts = [shift for _, shift in available_workers]
    staff_capacity = personnel_capacity(shifts, service.duration_minutes)

    if staff_capacity == 0 or len(available_workers) == 0:
        return DayAvailability(
            date=target_date,
            is_open=True,
            effective_quota=0,
            remaining_quota=0,
            slots=[],
            reason="NO_STAFF",
        )

    # 4. Quota check (QUOTA_FULL)
    eff_quota = effective_quota(day_config.max_appointments, staff_capacity)
    active_count = busy.active_count(target_date)
    rem_quota = max(eff_quota - active_count, 0)

    if rem_quota <= 0:
        return DayAvailability(
            date=target_date,
            is_open=True,
            effective_quota=eff_quota,
            remaining_quota=0,
            slots=[],
            reason="QUOTA_FULL",
        )

    # 5. Slot generation and filtering
    min_advance_hours = getattr(settings, "BOOKING_MIN_ADVANCE_HOURS", 2)
    min_advance_dt = current_local_dt + datetime.timedelta(hours=min_advance_hours)
    step_minutes = getattr(settings, "DEFAULT_SLOT_STEP_MINUTES", 15)

    busy_map = busy.busy_intervals(target_date)
    slot_worker_counts: dict[tuple[datetime.time, datetime.time], int] = {}

    for worker, shift in available_workers:
        worker_busy = busy_map.get(worker.id, [])
        candidate_slots = generate_slots(shift, service.duration_minutes, step_minutes)

        for candidate in candidate_slots:
            if any(candidate.overlaps(busy_interval) for busy_interval in worker_busy):
                continue

            slot_start_dt = datetime.datetime.combine(target_date, candidate.start, tzinfo=tz)
            if slot_start_dt < min_advance_dt:
                continue

            key = (candidate.start, candidate.end)
            slot_worker_counts[key] = slot_worker_counts.get(key, 0) + 1

    slots: list[Slot] = []
    for (start_t, end_t), count in sorted(slot_worker_counts.items(), key=lambda x: x[0][0]):
        if count >= 1:
            start_dt = datetime.datetime.combine(target_date, start_t, tzinfo=tz)
            end_dt = datetime.datetime.combine(target_date, end_t, tzinfo=tz)
            slots.append(Slot(start=start_dt, end=end_dt, free_workers=count))

    reason = "NO_SLOTS" if len(slots) == 0 else None

    return DayAvailability(
        date=target_date,
        is_open=True,
        effective_quota=eff_quota,
        remaining_quota=rem_quota,
        slots=slots,
        reason=reason,
    )
