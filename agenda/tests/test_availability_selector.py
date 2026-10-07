"""Tests for the availability selector in agenda/selectors/availability.py."""

import datetime

import pytest
from freezegun import freeze_time

from agenda.models import ExceptionKind, ScheduleException, Weekday, WorkSchedule
from agenda.selectors import get_day_availability
from agenda.services.capacity import Interval
from agenda.tests.factories import (
    DayConfigFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


class InMemoryBusySlots:
    """In-memory test double for BusySlotsPort."""

    def __init__(
        self,
        busy_map: dict[datetime.date, dict[int, list[Interval]]] | None = None,
        active_counts: dict[datetime.date, int] | None = None,
    ) -> None:
        self.busy_map = busy_map or {}
        self.active_counts = active_counts or {}

    def busy_intervals(self, target_date: datetime.date) -> dict[int, list[Interval]]:
        return self.busy_map.get(target_date, {})

    def active_count(self, target_date: datetime.date) -> int:
        return self.active_counts.get(target_date, 0)


@pytest.mark.django_db
class TestAvailabilitySelector:
    @freeze_time("2026-10-12 08:00:00-06:00")  # Monday
    def test_day_closed_returns_day_closed_reason(self):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)  # Wednesday

        DayConfigFactory(weekday=Weekday.WEDNESDAY, is_open=False)

        availability = get_day_availability(target_date, service)

        assert availability.is_open is False
        assert availability.reason == "DAY_CLOSED"
        assert availability.effective_quota == 0
        assert availability.remaining_quota == 0
        assert availability.slots == []

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_out_of_window_for_past_and_too_far_dates(self):
        service = ServiceFactory(duration_minutes=30)

        # Past date
        past_date = datetime.date(2026, 10, 11)
        avail_past = get_day_availability(past_date, service)
        assert avail_past.reason == "OUT_OF_WINDOW"
        assert avail_past.slots == []

        # Date beyond 60 days (e.g. 61 days ahead)
        future_date = datetime.date(2026, 10, 12) + datetime.timedelta(days=61)
        avail_future = get_day_availability(future_date, service)
        assert avail_future.reason == "OUT_OF_WINDOW"
        assert avail_future.slots == []

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_no_staff_reason_when_no_workers_available(self):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)  # Wednesday

        # Worker is inactive
        worker = WorkerFactory(is_active=False)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )

        availability = get_day_availability(target_date, service)
        assert availability.reason == "NO_STAFF"
        assert availability.effective_quota == 0
        assert availability.slots == []

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_special_hours_replaces_weekly_schedule(self):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)  # Wednesday

        worker = WorkerFactory(is_active=True)
        # Regular schedule: 09:00 - 17:00
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        # Exception: only 14:00 - 16:00
        ScheduleException.objects.create(
            worker=worker,
            date=target_date,
            kind=ExceptionKind.SPECIAL_HOURS,
            start_time=datetime.time(14, 0),
            end_time=datetime.time(16, 0),
        )

        availability = get_day_availability(target_date, service)
        assert availability.reason is None
        # 14:00-14:30, 14:15-14:45, 14:30-15:00, 14:45-15:15, 15:00-15:30, 15:15-15:45, 15:30-16:00
        slot_starts = [slot.start.time() for slot in availability.slots]
        assert slot_starts[0] == datetime.time(14, 0)
        assert slot_starts[-1] == datetime.time(15, 30)

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_busy_intervals_reduce_free_workers_and_remove_full_slots(self):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)  # Wednesday

        w1 = WorkerFactory(full_name="W1", is_active=True)
        WorkScheduleFactory(
            worker=w1,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(11, 0),
        )

        w2 = WorkerFactory(full_name="W2", is_active=True)
        WorkScheduleFactory(
            worker=w2,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(11, 0),
        )

        # W1 is busy at 09:00-09:30, W2 is busy at 09:30-10:00 and 09:00-09:30
        busy_adapter = InMemoryBusySlots(
            busy_map={
                target_date: {
                    w1.id: [Interval(datetime.time(9, 0), datetime.time(9, 30))],
                    w2.id: [
                        Interval(datetime.time(9, 0), datetime.time(9, 30)),
                        Interval(datetime.time(9, 30), datetime.time(10, 0)),
                    ],
                }
            }
        )

        availability = get_day_availability(target_date, service, busy=busy_adapter)

        # At 09:00-09:30, BOTH are busy -> Slot must NOT be offered
        slot_times = [(s.start.time(), s.end.time(), s.free_workers) for s in availability.slots]

        starts = [s[0] for s in slot_times]
        assert datetime.time(9, 0) not in starts

        # At 09:30-10:00, W1 is free and W2 is busy -> free_workers == 1
        slot_930 = next(s for s in slot_times if s[0] == datetime.time(9, 30))
        assert slot_930[2] == 1

        # At 10:00-10:30, BOTH are free -> free_workers == 2
        slot_1000 = next(s for s in slot_times if s[0] == datetime.time(10, 0))
        assert slot_1000[2] == 2

    @freeze_time("2026-10-12 08:30:00-06:00")  # Monday 08:30
    def test_booking_min_advance_hours_filters_today_early_slots(self):
        service = ServiceFactory(duration_minutes=30)
        today = datetime.date(2026, 10, 12)  # Same day

        worker = WorkerFactory(is_active=True)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )

        # Minimum advance is 2 hours -> slots before 10:30 must be filtered out
        availability = get_day_availability(today, service)

        assert availability.reason is None
        assert len(availability.slots) > 0
        first_slot = availability.slots[0]
        assert first_slot.start.time() >= datetime.time(10, 30)

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_quota_full_when_active_count_reaches_effective_quota(self):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)

        worker = WorkerFactory(is_active=True)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(11, 0),  # 4 slots
        )

        # DayConfig max_appointments is 3
        DayConfigFactory(weekday=Weekday.WEDNESDAY, max_appointments=3)

        # Active appointments in busy adapter = 3
        busy_adapter = InMemoryBusySlots(active_counts={target_date: 3})

        availability = get_day_availability(target_date, service, busy=busy_adapter)
        assert availability.reason == "QUOTA_FULL"
        assert availability.effective_quota == 3
        assert availability.remaining_quota == 0
        assert availability.slots == []

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_max_appointments_zero_gives_quota_full(self):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)

        worker = WorkerFactory(is_active=True)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )

        DayConfigFactory(weekday=Weekday.WEDNESDAY, max_appointments=0)

        availability = get_day_availability(target_date, service)
        assert availability.reason == "QUOTA_FULL"
        assert availability.effective_quota == 0
        assert availability.remaining_quota == 0
        assert availability.slots == []

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_no_slots_reason_when_all_slots_are_busy_but_quota_remains(self):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)

        worker = WorkerFactory(is_active=True)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(9, 30),  # Only 1 slot (09:00 - 09:30)
        )

        DayConfigFactory(weekday=Weekday.WEDNESDAY, max_appointments=10)

        # Worker is busy during the only slot, active_count is 0
        busy_adapter = InMemoryBusySlots(
            busy_map={
                target_date: {
                    worker.id: [Interval(datetime.time(9, 0), datetime.time(9, 30))],
                }
            },
            active_counts={target_date: 0},
        )

        availability = get_day_availability(target_date, service, busy=busy_adapter)
        assert availability.reason == "NO_SLOTS"
        assert availability.remaining_quota == 1
        assert availability.slots == []

    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_constant_query_count_regardless_of_worker_count(self, django_assert_max_num_queries):
        service = ServiceFactory(duration_minutes=30)
        target_date = datetime.date(2026, 10, 14)  # Wednesday

        # Create 10 workers with schedules
        for i in range(10):
            w = WorkerFactory(full_name=f"Worker {i}", is_active=True)
            WorkSchedule.objects.create(
                worker=w,
                weekday=Weekday.WEDNESDAY,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0),
            )

        # Constant queries: DayConfig (2) + Workers prefetches (3) + BusySlots (2) <= 8 queries
        with django_assert_max_num_queries(8):
            availability = get_day_availability(target_date, service)

        assert availability.reason is None
        assert len(availability.slots) > 0
        assert availability.slots[0].free_workers == 10
