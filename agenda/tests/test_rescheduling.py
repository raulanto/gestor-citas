"""Tests for appointment rescheduling domain logic."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from agenda.constants import AppointmentStatus
from agenda.exceptions import (
    DayClosed,
    InvalidSlot,
    NoWorkerAvailable,
    RescheduleLimitReached,
)
from agenda.models import Appointment, AppointmentEvent
from agenda.services.cancellation import reschedule_appointment
from agenda.tests.factories import (
    AppointmentFactory,
    DayConfigFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)

User = get_user_model()


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.fixture
def schedule_setup(tz):
    worker = WorkerFactory()
    # Schedules for Mon (0), Tue (1), Wed (2), Thu (3), Fri (4)
    for day in range(5):
        WorkScheduleFactory(
            worker=worker,
            weekday=day,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
    service = ServiceFactory(duration_minutes=30)
    return worker, service


@pytest.mark.django_db
def test_reschedule_success_confirmed_to_confirmed(schedule_setup, tz):
    worker, service = schedule_setup
    orig_date = datetime.date(2026, 10, 15)  # Thursday
    new_date = datetime.date(2026, 10, 16)  # Friday

    orig_start = datetime.datetime.combine(orig_date, datetime.time(10, 0), tzinfo=tz)
    orig_end = datetime.datetime.combine(orig_date, datetime.time(10, 30), tzinfo=tz)

    orig_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date,
        start_at=orig_start,
        end_at=orig_end,
        status=AppointmentStatus.CONFIRMED,
        reschedule_count=0,
    )

    new_start = datetime.datetime.combine(new_date, datetime.time(11, 0), tzinfo=tz)
    now = orig_start - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)
    user = User.objects.create_user(username="rescheduler")

    result = reschedule_appointment(
        orig_appt,
        new_start_at=new_start,
        actor=user,
        now=now,
    )

    new_appt = result.appointment
    orig_appt.refresh_from_db()

    # Original appointment
    assert orig_appt.status == AppointmentStatus.RESCHEDULED
    assert orig_appt.rescheduled_to == new_appt

    # New appointment
    assert new_appt.status == AppointmentStatus.CONFIRMED
    assert new_appt.worker == worker
    assert new_appt.rescheduled_from == orig_appt
    assert new_appt.reschedule_count == 1
    assert new_appt.date == new_date
    assert new_appt.start_at == new_start

    # Events recorded
    orig_event = AppointmentEvent.objects.filter(appointment=orig_appt).latest("created_at")
    assert orig_event.from_status == AppointmentStatus.CONFIRMED
    assert orig_event.to_status == AppointmentStatus.RESCHEDULED

    new_event = AppointmentEvent.objects.filter(appointment=new_appt).latest("created_at")
    assert new_event.to_status == AppointmentStatus.CONFIRMED


@pytest.mark.django_db
def test_reschedule_same_day_different_time_does_not_conflict_with_self(schedule_setup, tz):
    worker, service = schedule_setup
    target_date = datetime.date(2026, 10, 15)  # Thursday

    orig_start = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)
    new_start = datetime.datetime.combine(target_date, datetime.time(10, 30), tzinfo=tz)

    orig_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=orig_start,
        status=AppointmentStatus.CONFIRMED,
    )

    now = orig_start - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    result = reschedule_appointment(
        orig_appt,
        new_start_at=new_start,
        now=now,
    )

    assert result.appointment.status == AppointmentStatus.CONFIRMED
    assert result.appointment.start_at == new_start
    orig_appt.refresh_from_db()
    assert orig_appt.status == AppointmentStatus.RESCHEDULED


@pytest.mark.django_db
def test_reschedule_atomic_rollback_on_failure(schedule_setup, tz):
    worker, service = schedule_setup
    orig_date = datetime.date(2026, 10, 15)
    closed_date = datetime.date(2026, 10, 18)  # Sunday - closed

    orig_start = datetime.datetime.combine(orig_date, datetime.time(10, 0), tzinfo=tz)
    orig_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date,
        start_at=orig_start,
        status=AppointmentStatus.CONFIRMED,
    )
    initial_events_count = AppointmentEvent.objects.filter(appointment=orig_appt).count()
    initial_appts_count = Appointment.objects.count()

    DayConfigFactory(date=closed_date, weekday=None, is_open=False)
    now = orig_start - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)
    new_start_closed = datetime.datetime.combine(closed_date, datetime.time(10, 0), tzinfo=tz)

    with pytest.raises(DayClosed):
        reschedule_appointment(orig_appt, new_start_at=new_start_closed, now=now)

    orig_appt.refresh_from_db()
    assert orig_appt.status == AppointmentStatus.CONFIRMED
    assert Appointment.objects.count() == initial_appts_count
    assert AppointmentEvent.objects.filter(appointment=orig_appt).count() == initial_events_count


@pytest.mark.django_db
def test_reschedule_limit_reached_and_force_bypass(schedule_setup, tz):
    worker, service = schedule_setup
    orig_date = datetime.date(2026, 10, 15)
    new_date = datetime.date(2026, 10, 16)

    orig_start = datetime.datetime.combine(orig_date, datetime.time(10, 0), tzinfo=tz)
    new_start = datetime.datetime.combine(new_date, datetime.time(10, 0), tzinfo=tz)
    now = orig_start - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    max_limit = getattr(settings, "MAX_RESCHEDULES_PER_APPOINTMENT", 2)
    orig_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date,
        start_at=orig_start,
        status=AppointmentStatus.CONFIRMED,
        reschedule_count=max_limit,
    )

    # Rejection for normal user
    with pytest.raises(RescheduleLimitReached):
        reschedule_appointment(orig_appt, new_start_at=new_start, now=now)

    # Success when force=True
    staff_user = User.objects.create_superuser(username="admin_resched")
    result = reschedule_appointment(
        orig_appt,
        new_start_at=new_start,
        force=True,
        actor=staff_user,
        now=now,
    )
    assert result.appointment.status == AppointmentStatus.CONFIRMED
    assert result.appointment.reschedule_count == max_limit + 1


@pytest.mark.django_db
def test_reschedule_no_degradation_rule(schedule_setup, tz):
    worker, service = schedule_setup
    orig_date = datetime.date(2026, 10, 15)
    new_date = datetime.date(2026, 10, 16)

    orig_start = datetime.datetime.combine(orig_date, datetime.time(10, 0), tzinfo=tz)
    new_start = datetime.datetime.combine(new_date, datetime.time(10, 0), tzinfo=tz)
    now = orig_start - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    # Pre-occupy worker on new date at 10:00
    AppointmentFactory(
        service=service,
        worker=worker,
        date=new_date,
        start_at=new_start,
        status=AppointmentStatus.CONFIRMED,
    )

    orig_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date,
        start_at=orig_start,
        status=AppointmentStatus.CONFIRMED,
    )

    # 1. By default allow_waitlist=False -> raises NoWorkerAvailable, rollback
    with pytest.raises(NoWorkerAvailable):
        reschedule_appointment(orig_appt, new_start_at=new_start, allow_waitlist=False, now=now)
    orig_appt.refresh_from_db()
    assert orig_appt.status == AppointmentStatus.CONFIRMED

    # 2. With allow_waitlist=True -> allowed to become WAITLISTED
    result = reschedule_appointment(orig_appt, new_start_at=new_start, allow_waitlist=True, now=now)
    assert result.appointment.status == AppointmentStatus.WAITLISTED
    assert result.appointment.worker is None
    orig_appt.refresh_from_db()
    assert orig_appt.status == AppointmentStatus.RESCHEDULED


@pytest.mark.django_db
def test_reschedule_same_slot_rejected(schedule_setup, tz):
    worker, service = schedule_setup
    orig_date = datetime.date(2026, 10, 15)
    orig_start = datetime.datetime.combine(orig_date, datetime.time(10, 0), tzinfo=tz)

    orig_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date,
        start_at=orig_start,
        status=AppointmentStatus.CONFIRMED,
    )
    now = orig_start - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)

    with pytest.raises(InvalidSlot):
        reschedule_appointment(orig_appt, new_start_at=orig_start, now=now)
