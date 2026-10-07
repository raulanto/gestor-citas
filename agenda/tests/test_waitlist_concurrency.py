"""Concurrency tests for waitlist processing with ThreadPoolExecutor."""

import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection

from agenda.constants import AppointmentStatus
from agenda.models import Appointment, AppointmentEvent, Weekday
from agenda.services.booking import book_appointment
from agenda.services.waitlist import process_waitlist
from agenda.tests.factories import (
    AppointmentFactory,
    DayConfigFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db(transaction=True)
def test_concurrent_waitlist_processing_threads(tz):
    """4 threads running process_waitlist: each appointment is assigned exactly once."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )

    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    # Create 4 waitlisted appointments in non-overlapping slots
    appts = []
    for hour in (9, 10, 11, 12):
        start_at = datetime.datetime(2026, 10, 12, hour, 0, tzinfo=tz)
        end_at = start_at + datetime.timedelta(minutes=30)
        appt = AppointmentFactory(
            worker=None,
            service=service,
            date=target_date,
            start_at=start_at,
            end_at=end_at,
            status=AppointmentStatus.WAITLISTED,
        )
        appts.append(appt)

    def run_process():
        try:
            return process_waitlist(target_date, now=now_dt)
        finally:
            connection.close()

    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_process) for _ in range(4)]
        for future in as_completed(futures):
            res = future.result()
            results.append(res)

    total_assigned_across_threads = sum(len(r.assigned) for r in results)
    assert total_assigned_across_threads == 4

    # Verify each appointment is confirmed exactly once
    for appt in appts:
        appt.refresh_from_db()
        assert appt.status == AppointmentStatus.CONFIRMED
        assert appt.worker == worker
        # Exactly one promotion event per appointment
        events = AppointmentEvent.objects.filter(
            appointment=appt,
            to_status=AppointmentStatus.CONFIRMED,
        )
        assert events.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_booking_and_waitlist_processing(tz):
    """Simultaneous booking and waitlist: never creates overlapping confirmed appointments."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )

    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)
    slot_start = datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz)
    slot_end = slot_start + datetime.timedelta(minutes=30)

    # One existing waitlisted appointment for 10:00
    AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=slot_start,
        end_at=slot_end,
        status=AppointmentStatus.WAITLISTED,
    )

    # Prepare another requester trying to book 10:00 at the same time
    new_requester = RequesterFactory(phone="5559998887")

    def run_booking():
        try:
            return book_appointment(
                requester=new_requester,
                service=service,
                start_at=slot_start,
                now=now_dt,
            )
        finally:
            connection.close()

    def run_waitlist():
        try:
            return process_waitlist(target_date, now=now_dt)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_book = executor.submit(run_booking)
        f_waitlist = executor.submit(run_waitlist)
        f_book.result()
        f_waitlist.result()

    # Verify at most ONE appointment is CONFIRMED for that worker & slot
    confirmed_appts = Appointment.objects.filter(
        date=target_date,
        worker=worker,
        start_at=slot_start,
        status=AppointmentStatus.CONFIRMED,
    )
    assert confirmed_appts.count() == 1
