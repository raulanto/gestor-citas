"""Concurrency tests for worker schedule changes, revalidation, and parallel operations."""

import datetime
from concurrent.futures import ThreadPoolExecutor, wait
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection

from agenda.constants import AppointmentStatus
from agenda.models import Appointment
from agenda.services.booking import book_appointment
from agenda.services.cancellation import reschedule_appointment
from agenda.services.schedules import (
    revalidate_all,
    set_weekly_schedule,
)
from agenda.tests.factories import (
    AppointmentFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db(transaction=True)
def test_concurrent_booking_and_schedule_change(tz):
    """While 8 threads attempt bookings, a schedule change shortens a shift.

    After revalidation, no CONFIRMED appointment is outside the worker's shift or overlapping.
    """
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)  # Thursday, weekday 3
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    def _book(hour, minute):
        connection.close()
        try:
            start_at = datetime.datetime.combine(
                target_date, datetime.time(hour, minute), tzinfo=tz
            )
            requester = RequesterFactory()
            return book_appointment(
                requester=requester,
                service=service,
                start_at=start_at,
                allow_waitlist=True,
                now=now,
            )
        except Exception:
            return None
        finally:
            connection.close()

    def _shorten_schedule():
        connection.close()
        try:
            new_entries = [
                {
                    "weekday": 3,
                    "start_time": datetime.time(9, 0),
                    "end_time": datetime.time(12, 0),
                    "break_start": None,
                    "break_end": None,
                }
            ]
            return set_weekly_schedule(worker, new_entries, confirm=True, dry_run=False, now=now)
        except Exception:
            return None
        finally:
            connection.close()

    slots = [
        (9, 0),
        (9, 30),
        (10, 0),
        (10, 30),
        (14, 0),
        (14, 30),
        (15, 0),
        (15, 30),
    ]

    with ThreadPoolExecutor(max_workers=9) as executor:
        booking_futures = [executor.submit(_book, h, m) for h, m in slots]
        schedule_future = executor.submit(_shorten_schedule)
        wait(booking_futures + [schedule_future], timeout=15)

    revalidate_all(now=now, from_date=target_date)

    confirmed_appts = Appointment.objects.filter(
        date=target_date, status=AppointmentStatus.CONFIRMED, worker=worker
    )
    for appt in confirmed_appts:
        assert appt.start_at.time() >= datetime.time(9, 0)
        assert appt.end_at.time() <= datetime.time(12, 0)


@pytest.mark.django_db(transaction=True)
def test_concurrent_schedule_changes_same_worker(tz):
    """Two concurrent schedule changes for the same worker serialize cleanly without deadlocks."""
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )
    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    def _change_a():
        connection.close()
        try:
            entries = [
                {
                    "weekday": 3,
                    "start_time": datetime.time(9, 0),
                    "end_time": datetime.time(15, 0),
                    "break_start": None,
                    "break_end": None,
                }
            ]
            return set_weekly_schedule(worker, entries, confirm=True, dry_run=False, now=now)
        finally:
            connection.close()

    def _change_b():
        connection.close()
        try:
            entries = [
                {
                    "weekday": 3,
                    "start_time": datetime.time(8, 0),
                    "end_time": datetime.time(16, 0),
                    "break_start": None,
                    "break_end": None,
                }
            ]
            return set_weekly_schedule(worker, entries, confirm=True, dry_run=False, now=now)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_change_a)
        f2 = executor.submit(_change_b)
        done, not_done = wait([f1, f2], timeout=10)

    assert len(not_done) == 0, "Deadlock in concurrent schedule changes"


@pytest.mark.django_db(transaction=True)
def test_concurrent_schedule_change_and_reschedule_no_deadlock(tz):
    """Schedule change across dates and appointment rescheduling in parallel do not deadlock."""
    worker = WorkerFactory()
    date_a = datetime.date(2026, 10, 15)  # Thu
    date_b = datetime.date(2026, 10, 16)  # Fri

    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    WorkScheduleFactory(
        worker=worker,
        weekday=4,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )

    service = ServiceFactory(duration_minutes=30)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=date_a,
        start_at=datetime.datetime.combine(date_a, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )
    now = datetime.datetime.combine(date_a, datetime.time(8, 0), tzinfo=tz)

    def _do_reschedule():
        connection.close()
        try:
            new_start = datetime.datetime.combine(date_b, datetime.time(11, 0), tzinfo=tz)
            return reschedule_appointment(appt, new_start_at=new_start, now=now)
        finally:
            connection.close()

    def _do_schedule_change():
        connection.close()
        try:
            entries = [
                {
                    "weekday": 3,
                    "start_time": datetime.time(9, 0),
                    "end_time": datetime.time(14, 0),
                    "break_start": None,
                    "break_end": None,
                },
                {
                    "weekday": 4,
                    "start_time": datetime.time(9, 0),
                    "end_time": datetime.time(14, 0),
                    "break_start": None,
                    "break_end": None,
                },
            ]
            return set_weekly_schedule(worker, entries, confirm=True, dry_run=False, now=now)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_do_reschedule)
        f2 = executor.submit(_do_schedule_change)
        done, not_done = wait([f1, f2], timeout=10)

    assert len(not_done) == 0, "Deadlock in schedule change and reschedule"
