"""Concurrency tests for appointment booking with ThreadPoolExecutor."""

import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection

from agenda.constants import AppointmentStatus
from agenda.exceptions import QuotaExceeded
from agenda.models import Appointment, Weekday
from agenda.services.booking import book_appointment
from agenda.tests.factories import (
    DayConfigFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.mark.django_db(transaction=True)
def test_concurrent_booking_quota_limit():
    """8 concurrent requests with quota=1: exactly 1 created, 7 QuotaExceeded."""
    tz = ZoneInfo(settings.TIME_ZONE)
    target_date = datetime.date(2026, 10, 12)
    start_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    now_dt = datetime.datetime(2026, 10, 10, 10, 0, tzinfo=tz)

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
        max_appointments=1,
    )

    requesters = [RequesterFactory(phone=f"555000000{i}") for i in range(8)]
    results = []
    errors = []

    def attempt_booking(requester):
        try:
            return book_appointment(
                requester=requester,
                service=service,
                start_at=start_at,
                now=now_dt,
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(attempt_booking, req): req for req in requesters}
        for future in as_completed(futures):
            try:
                res = future.result()
                results.append(res)
            except QuotaExceeded as exc:
                errors.append(exc)

    assert len(results) == 1
    assert len(errors) == 7
    assert Appointment.objects.filter(date=target_date).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_booking_same_slot_one_worker():
    """1 worker, same slot, 8 concurrent requests: exactly 1 CONFIRMED, 7 WAITLISTED."""
    tz = ZoneInfo(settings.TIME_ZONE)
    target_date = datetime.date(2026, 10, 12)
    start_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    now_dt = datetime.datetime(2026, 10, 10, 10, 0, tzinfo=tz)

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

    requesters = [RequesterFactory(phone=f"555111111{i}") for i in range(8)]
    results = []

    def attempt_booking(requester):
        try:
            return book_appointment(
                requester=requester,
                service=service,
                start_at=start_at,
                now=now_dt,
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(attempt_booking, req): req for req in requesters}
        for future in as_completed(futures):
            res = future.result()
            results.append(res)

    confirmed = [r for r in results if r.outcome == AppointmentStatus.CONFIRMED]
    waitlisted = [r for r in results if r.outcome == AppointmentStatus.WAITLISTED]

    assert len(confirmed) == 1
    assert len(waitlisted) == 7

    # Verify database state
    assert (
        Appointment.objects.filter(
            date=target_date,
            status=AppointmentStatus.CONFIRMED,
        ).count()
        == 1
    )
    assert (
        Appointment.objects.filter(
            date=target_date,
            status=AppointmentStatus.WAITLISTED,
        ).count()
        == 7
    )
