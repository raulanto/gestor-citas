import datetime

import pytest

from agenda.models import (
    DayConfig,
    ExceptionKind,
    ScheduleException,
    Weekday,
    WorkSchedule,
)
from agenda.selectors import (
    DayConfigResolved,
    Shift,
    list_available_workers_on,
    resolve_day_config,
    resolve_worker_shift,
)
from agenda.tests.factories import (
    DayConfigFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.mark.django_db
class TestDayConfigSelector:
    def test_fallback_when_no_config_exists(self):
        target_date = datetime.date(2026, 10, 14)  # Wednesday
        resolved = resolve_day_config(target_date)

        assert isinstance(resolved, DayConfigResolved)
        assert resolved.date == target_date
        assert resolved.is_open is True
        assert resolved.max_appointments is None
        assert resolved.source == "fallback"

    def test_weekday_default_resolved(self):
        target_date = datetime.date(2026, 10, 14)  # Wednesday (weekday 2)
        DayConfigFactory(
            weekday=Weekday.WEDNESDAY,
            date=None,
            is_open=True,
            max_appointments=18,
        )

        resolved = resolve_day_config(target_date)

        assert resolved.date == target_date
        assert resolved.is_open is True
        assert resolved.max_appointments == 18
        assert resolved.source == "weekday_default"

    def test_date_override_takes_precedence_over_weekday_default(self):
        target_date = datetime.date(2026, 10, 14)  # Wednesday (weekday 2)
        # Weekday default: open, 20
        DayConfigFactory(
            weekday=Weekday.WEDNESDAY,
            date=None,
            is_open=True,
            max_appointments=20,
        )
        # Date override: closed, 0
        DayConfig.objects.create(
            date=target_date,
            weekday=None,
            is_open=False,
            max_appointments=0,
            note="Mantenimiento extraordinario",
        )

        resolved = resolve_day_config(target_date)

        assert resolved.date == target_date
        assert resolved.is_open is False
        assert resolved.max_appointments == 0
        assert resolved.source == "date_override"

    def test_domain_settings_fallback_to_defaults(self):
        target_date = datetime.date(2026, 10, 14)
        resolved = resolve_day_config(target_date)

        assert resolved.booking_min_advance_hours == 2
        assert resolved.booking_max_advance_days == 60
        assert resolved.cancel_min_hours == 4
        assert resolved.max_reschedules_per_appointment == 2
        assert resolved.max_active_per_requester_per_day == 1
        assert resolved.waitlist_max_per_day == 20
        assert resolved.default_slot_step_minutes == 15

    def test_domain_settings_hierarchical_resolution(self):
        target_date = datetime.date(2026, 10, 14)  # Wednesday (weekday 2)
        # Weekday default sets some parameters
        DayConfig.objects.create(
            weekday=Weekday.WEDNESDAY,
            date=None,
            is_open=True,
            booking_min_advance_hours=6,
            cancel_min_hours=12,
            waitlist_max_per_day=5,
        )
        # Date override sets one parameter specifically
        DayConfig.objects.create(
            date=target_date,
            weekday=None,
            is_open=True,
            booking_min_advance_hours=1,  # Overrides weekday's 6
            # cancel_min_hours is None -> should cascade to weekday's 12
            # booking_max_advance_days is None on both -> should cascade to settings (60)
        )

        resolved = resolve_day_config(target_date)
        assert resolved.source == "date_override"
        assert resolved.booking_min_advance_hours == 1  # From date override
        assert resolved.cancel_min_hours == 12  # From weekday default
        assert resolved.waitlist_max_per_day == 5  # From weekday default
        assert resolved.booking_max_advance_days == 60  # From settings fallback


@pytest.mark.django_db
class TestWorkerShiftSelectors:
    def test_inactive_worker_returns_none(self):
        worker = WorkerFactory(is_active=False)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        target_date = datetime.date(2026, 10, 12)  # Monday

        shift = resolve_worker_shift(worker, target_date)
        assert shift is None

    def test_absence_exception_returns_none(self):
        worker = WorkerFactory(is_active=True)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        target_date = datetime.date(2026, 10, 12)  # Monday
        ScheduleException.objects.create(
            worker=worker,
            date=target_date,
            kind=ExceptionKind.ABSENCE,
            reason="Incapacidad",
        )

        shift = resolve_worker_shift(worker, target_date)
        assert shift is None

    def test_special_hours_exception_overrides_weekly_schedule(self):
        worker = WorkerFactory(is_active=True)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        target_date = datetime.date(2026, 10, 12)  # Monday
        ScheduleException.objects.create(
            worker=worker,
            date=target_date,
            kind=ExceptionKind.SPECIAL_HOURS,
            start_time=datetime.time(12, 0),
            end_time=datetime.time(20, 0),
            break_start=datetime.time(15, 0),
            break_end=datetime.time(16, 0),
        )

        shift = resolve_worker_shift(worker, target_date)
        assert shift is not None
        assert shift == Shift(
            start=datetime.time(12, 0),
            end=datetime.time(20, 0),
            break_start=datetime.time(15, 0),
            break_end=datetime.time(16, 0),
        )

    def test_regular_schedule_used_when_no_exception(self):
        worker = WorkerFactory(is_active=True)
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(8, 30),
            end_time=datetime.time(16, 30),
            break_start=datetime.time(12, 0),
            break_end=datetime.time(13, 0),
        )
        target_date = datetime.date(2026, 10, 12)  # Monday

        shift = resolve_worker_shift(worker, target_date)
        assert shift is not None
        assert shift == Shift(
            start=datetime.time(8, 30),
            end=datetime.time(16, 30),
            break_start=datetime.time(12, 0),
            break_end=datetime.time(13, 0),
        )

    def test_no_schedule_and_no_exception_returns_none(self):
        worker = WorkerFactory(is_active=True)
        # Worker only works on Tuesday
        WorkScheduleFactory(
            worker=worker,
            weekday=Weekday.TUESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        target_date = datetime.date(2026, 10, 12)  # Monday

        shift = resolve_worker_shift(worker, target_date)
        assert shift is None

    def test_list_available_workers_on_filters_and_resolves(self, django_assert_num_queries):
        target_date = datetime.date(2026, 10, 12)  # Monday

        # Worker 1: Active, regular schedule -> Available
        w1 = WorkerFactory(full_name="Worker 1", is_active=True)
        WorkSchedule.objects.create(
            worker=w1,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )

        # Worker 2: Active, regular schedule, but ABSENCE on target_date -> Not available
        w2 = WorkerFactory(full_name="Worker 2", is_active=True)
        WorkSchedule.objects.create(
            worker=w2,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        ScheduleException.objects.create(
            worker=w2,
            date=target_date,
            kind=ExceptionKind.ABSENCE,
        )

        # Worker 3: Inactive with schedule -> Not available
        w3 = WorkerFactory(full_name="Worker 3", is_active=False)
        WorkSchedule.objects.create(
            worker=w3,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )

        # Worker 4: Active, no regular schedule for Monday, but SPECIAL_HOURS -> Available
        w4 = WorkerFactory(full_name="Worker 4", is_active=True)
        ScheduleException.objects.create(
            worker=w4,
            date=target_date,
            kind=ExceptionKind.SPECIAL_HOURS,
            start_time=datetime.time(14, 0),
            end_time=datetime.time(18, 0),
        )

        # Execute query and ensure constant query count (Workers + Exceptions + Schedules)
        with django_assert_num_queries(3):
            available = list_available_workers_on(target_date)

        available_worker_ids = [worker.id for worker, _ in available]
        assert available_worker_ids == [w1.id, w4.id]

        # Verify shifts
        shift_map = {worker.id: shift for worker, shift in available}
        assert shift_map[w1.id].start == datetime.time(9, 0)
        assert shift_map[w4.id].start == datetime.time(14, 0)
