"""Tests for schedule change services with confirmation and dry-run flows."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings

from agenda.constants import AppointmentStatus
from agenda.exceptions import ScheduleChangeNeedsConfirmation
from agenda.models import Appointment, ExceptionKind, ScheduleException, WorkSchedule
from agenda.services.schedules import (
    add_exception,
    remove_exception,
    set_weekly_schedule,
    set_worker_active,
)
from agenda.tests.factories import (
    AppointmentFactory,
    ScheduleExceptionFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db
def test_set_weekly_schedule_requires_confirmation_on_impact(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)  # Thursday, weekday=3
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    start_at = datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    new_entries = [
        {
            "weekday": 3,
            "start_time": datetime.time(9, 0),
            "end_time": datetime.time(12, 0),  # Displaces 15:00 appointment
            "break_start": None,
            "break_end": None,
        }
    ]

    # 1. Without confirm: raises exception with impact and leaves DB untouched
    with pytest.raises(ScheduleChangeNeedsConfirmation) as exc_info:
        set_weekly_schedule(worker, new_entries, confirm=False, dry_run=False, now=now)

    assert exc_info.value.code == "SCHEDULE_CHANGE_REQUIRES_CONFIRMATION"
    assert exc_info.value.impact is not None
    assert exc_info.value.impact["waitlisted"] == 1
    assert len(exc_info.value.impact["displaced"]) == 1

    # Verify DB was NOT modified
    ws = WorkSchedule.objects.get(worker=worker, weekday=3)
    assert ws.end_time == datetime.time(17, 0)
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == worker

    # 2. With dry_run=True: returns applied=False with impact, does NOT modify DB
    res_dry = set_weekly_schedule(worker, new_entries, confirm=False, dry_run=True, now=now)
    assert res_dry.applied is False
    assert res_dry.impact.waitlisted == 1
    ws.refresh_from_db()
    assert ws.end_time == datetime.time(17, 0)
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED

    # 3. With confirm=True: applies changes to DB
    res_conf = set_weekly_schedule(worker, new_entries, confirm=True, dry_run=False, now=now)
    assert res_conf.applied is True
    assert res_conf.impact.waitlisted == 1
    ws.refresh_from_db()
    assert ws.end_time == datetime.time(12, 0)
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
    assert appt.worker is None


@pytest.mark.django_db
def test_set_weekly_schedule_applies_without_confirmation_when_no_impact(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(14, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    # Expand to 17:00 (no displacement)
    new_entries = [
        {
            "weekday": 3,
            "start_time": datetime.time(9, 0),
            "end_time": datetime.time(17, 0),
            "break_start": None,
            "break_end": None,
        }
    ]

    res = set_weekly_schedule(worker, new_entries, confirm=False, dry_run=False, now=now)
    assert res.applied is True
    assert len(res.impact.displaced) == 0

    ws = WorkSchedule.objects.get(worker=worker, weekday=3)
    assert ws.end_time == datetime.time(17, 0)
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED


@pytest.mark.django_db
def test_add_exception_requires_confirmation_on_impact(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    start_at = datetime.datetime.combine(target_date, datetime.time(11, 0), tzinfo=tz)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    exc_data = {
        "date": target_date,
        "kind": ExceptionKind.ABSENCE,
        "reason": "Vacaciones",
    }

    # Without confirmation
    with pytest.raises(ScheduleChangeNeedsConfirmation) as exc_info:
        add_exception(worker, exc_data, confirm=False, dry_run=False, now=now)

    assert exc_info.value.impact["waitlisted"] == 1
    assert ScheduleException.objects.filter(worker=worker, date=target_date).count() == 0
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED

    # With dry run
    res_dry = add_exception(worker, exc_data, confirm=False, dry_run=True, now=now)
    assert res_dry.applied is False
    assert ScheduleException.objects.filter(worker=worker, date=target_date).count() == 0

    # With confirmation
    res_conf = add_exception(worker, exc_data, confirm=True, dry_run=False, now=now)
    assert res_conf.applied is True
    assert ScheduleException.objects.filter(worker=worker, date=target_date).count() == 1
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED


@pytest.mark.django_db
def test_remove_exception_flow(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    exc = ScheduleExceptionFactory(
        worker=worker,
        date=target_date,
        kind=ExceptionKind.ABSENCE,
    )
    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    res = remove_exception(exc, confirm=False, dry_run=False, now=now)
    assert res.applied is True
    assert not ScheduleException.objects.filter(id=exc.id).exists()


@pytest.mark.django_db
def test_set_worker_active_requires_confirmation_on_deactivation(tz):
    worker = WorkerFactory(is_active=True)
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    start_at = datetime.datetime.combine(target_date, datetime.time(11, 0), tzinfo=tz)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )
    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    # Deactivating worker with appointments without confirm
    with pytest.raises(ScheduleChangeNeedsConfirmation) as exc_info:
        set_worker_active(worker, False, confirm=False, dry_run=False, now=now)

    assert exc_info.value.impact["waitlisted"] == 1
    worker.refresh_from_db()
    assert worker.is_active is True
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED

    # Deactivating with confirm=True
    res = set_worker_active(worker, False, confirm=True, dry_run=False, now=now)
    assert res.applied is True
    worker.refresh_from_db()
    assert worker.is_active is False
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
