"""Concurrency tests for cancellation and rescheduling."""

import datetime
from concurrent.futures import ThreadPoolExecutor, wait
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection

from agenda.constants import AppointmentStatus
from agenda.models import AppointmentEvent
from agenda.services.cancellation import cancel_appointment, reschedule_appointment
from agenda.tests.factories import (
    AppointmentFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db(transaction=True)
def test_concurrent_cancellations_single_event(tz):
    worker = WorkerFactory()
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    appointment = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )
    now = start_at - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    def _cancel():
        connection.close()
        try:
            cancel_appointment(appointment, reason="Cancelación concurrente", now=now)
            return True
        except Exception:
            return False
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_cancel) for _ in range(8)]
        for f in futures:
            f.result()

    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CANCELLED
    # Exactly one cancel event
    events = AppointmentEvent.objects.filter(
        appointment=appointment, to_status=AppointmentStatus.CANCELLED
    )
    assert events.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_cancel_and_reschedule(tz):
    worker = WorkerFactory()
    for day in range(5):
        WorkScheduleFactory(
            worker=worker,
            weekday=day,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
    service = ServiceFactory(duration_minutes=30)
    orig_date = datetime.date(2026, 10, 15)  # Thu
    new_date = datetime.date(2026, 10, 16)  # Fri

    orig_start = datetime.datetime.combine(orig_date, datetime.time(10, 0), tzinfo=tz)
    new_start = datetime.datetime.combine(new_date, datetime.time(11, 0), tzinfo=tz)

    appointment = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date,
        start_at=orig_start,
        status=AppointmentStatus.CONFIRMED,
    )
    now = orig_start - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    cancel_res = []
    resched_res = []

    def _do_cancel():
        connection.close()
        try:
            cancel_appointment(appointment, reason="Cancel concurrently", now=now)
            cancel_res.append(True)
        except Exception:
            cancel_res.append(False)
        finally:
            connection.close()

    def _do_reschedule():
        connection.close()
        try:
            res = reschedule_appointment(appointment, new_start_at=new_start, now=now)
            resched_res.append(res.appointment)
        except Exception:
            resched_res.append(False)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_do_cancel)
        f2 = executor.submit(_do_reschedule)
        wait([f1, f2], timeout=5)

    appointment.refresh_from_db()
    # Either cancel won or reschedule won
    if True in cancel_res and resched_res[0] is not False:
        pass
    assert appointment.status in (AppointmentStatus.CANCELLED, AppointmentStatus.RESCHEDULED)


@pytest.mark.django_db(transaction=True)
def test_cross_day_rescheduling_no_deadlock(tz):
    worker = WorkerFactory()
    for day in range(5):
        WorkScheduleFactory(
            worker=worker,
            weekday=day,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
    service = ServiceFactory(duration_minutes=30)
    date_a = datetime.date(2026, 10, 15)
    date_b = datetime.date(2026, 10, 16)

    start_a1 = datetime.datetime.combine(date_a, datetime.time(9, 0), tzinfo=tz)
    start_a2 = datetime.datetime.combine(date_a, datetime.time(10, 0), tzinfo=tz)
    start_b1 = datetime.datetime.combine(date_b, datetime.time(9, 0), tzinfo=tz)
    start_b2 = datetime.datetime.combine(date_b, datetime.time(10, 0), tzinfo=tz)

    appt_a = AppointmentFactory(
        service=service,
        worker=worker,
        date=date_a,
        start_at=start_a1,
        status=AppointmentStatus.CONFIRMED,
    )
    appt_b = AppointmentFactory(
        service=service,
        worker=worker,
        date=date_b,
        start_at=start_b1,
        status=AppointmentStatus.CONFIRMED,
    )

    now = start_a1 - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    def _resched_a_to_b():
        connection.close()
        try:
            return reschedule_appointment(appt_a, new_start_at=start_b2, now=now)
        finally:
            connection.close()

    def _resched_b_to_a():
        connection.close()
        try:
            return reschedule_appointment(appt_b, new_start_at=start_a2, now=now)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_a = executor.submit(_resched_a_to_b)
        f_b = executor.submit(_resched_b_to_a)
        done, not_done = wait([f_a, f_b], timeout=10)

    assert len(not_done) == 0, "Deadlock occurred during cross-day rescheduling!"


@pytest.mark.django_db(transaction=True)
def test_concurrent_reschedule_competing_for_last_slot(tz):
    worker = WorkerFactory()
    for day in range(5):
        WorkScheduleFactory(
            worker=worker,
            weekday=day,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
    service = ServiceFactory(duration_minutes=30)
    orig_date_1 = datetime.date(2026, 10, 15)
    orig_date_2 = datetime.date(2026, 10, 15)
    target_date = datetime.date(2026, 10, 16)

    start_1 = datetime.datetime.combine(orig_date_1, datetime.time(9, 0), tzinfo=tz)
    start_2 = datetime.datetime.combine(orig_date_2, datetime.time(10, 0), tzinfo=tz)
    target_slot = datetime.datetime.combine(target_date, datetime.time(14, 0), tzinfo=tz)

    appt1 = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date_1,
        start_at=start_1,
        status=AppointmentStatus.CONFIRMED,
    )
    appt2 = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date_2,
        start_at=start_2,
        status=AppointmentStatus.CONFIRMED,
    )

    now = start_1 - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    def _resched(appt):
        connection.close()
        try:
            res = reschedule_appointment(
                appt, new_start_at=target_slot, allow_waitlist=False, now=now
            )
            return ("SUCCESS", res.appointment)
        except Exception:
            return ("FAILED", "Error")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_resched, appt1)
        f2 = executor.submit(_resched, appt2)
        done, not_done = wait([f1, f2], timeout=10)

    results = [f.result()[0] for f in [f1, f2]]
    assert results.count("SUCCESS") == 1
    assert results.count("FAILED") == 1

    # Winner confirmed at target_slot, loser rolled back and retains confirmed appointment
    appt1.refresh_from_db()
    appt2.refresh_from_db()
    statuses = [appt1.status, appt2.status]
    assert AppointmentStatus.CONFIRMED in statuses
    assert AppointmentStatus.RESCHEDULED in statuses
