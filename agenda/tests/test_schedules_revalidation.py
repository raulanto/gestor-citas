"""Tests for worker schedule revalidation logic."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from agenda.constants import AppointmentStatus, EventNote
from agenda.models import Appointment, AppointmentEvent, ExceptionKind
from agenda.selectors.schedules import list_unserviceable_waitlist
from agenda.services.schedules import revalidate_all, revalidate_worker
from agenda.tests.factories import (
    AppointmentFactory,
    DayConfigFactory,
    ScheduleExceptionFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)

User = get_user_model()


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db
def test_shortening_shift_displaces_only_late_appointments(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)  # Thursday (weekday 3)

    # Initial schedule: 09:00 - 17:00
    schedule = WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)

    # Early appointment (10:00 - 10:30)
    early_start = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)
    appt_early = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=early_start,
        status=AppointmentStatus.CONFIRMED,
    )

    # Late appointment (15:00 - 15:30)
    late_start = datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz)
    appt_late = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=late_start,
        status=AppointmentStatus.CONFIRMED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    # Shorten shift: 09:00 - 14:00
    schedule.end_time = datetime.time(14, 0)
    schedule.save()

    result = revalidate_worker(worker.id, now=now)

    assert len(result.displaced) == 1
    assert result.displaced[0].appointment_id == appt_late.id

    appt_early.refresh_from_db()
    appt_late.refresh_from_db()

    assert appt_early.status == AppointmentStatus.CONFIRMED
    assert appt_early.worker == worker

    assert appt_late.status == AppointmentStatus.WAITLISTED
    assert appt_late.worker is None


@pytest.mark.django_db
def test_reassignment_to_alternative_worker(tz):
    worker1 = WorkerFactory(full_name="Trabajador 1")
    worker2 = WorkerFactory(full_name="Trabajador 2")
    target_date = datetime.date(2026, 10, 15)

    WorkScheduleFactory(
        worker=worker1,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(14, 0),  # Will no longer cover 15:00
    )
    WorkScheduleFactory(
        worker=worker2,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),  # Covers 15:00 and is free
    )
    service = ServiceFactory(duration_minutes=30)

    late_start = datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz)
    appt = AppointmentFactory(
        service=service,
        worker=worker1,
        date=target_date,
        start_at=late_start,
        status=AppointmentStatus.CONFIRMED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)
    result = revalidate_worker(worker1.id, now=now)

    assert result.reassigned == 1
    assert result.waitlisted == 0
    appt.refresh_from_db()

    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == worker2

    # Check event
    event = AppointmentEvent.objects.filter(appointment=appt).latest("created_at")
    assert event.from_status == AppointmentStatus.CONFIRMED
    assert event.to_status == AppointmentStatus.CONFIRMED
    assert event.worker == worker2
    assert event.note == EventNote.REASSIGNED_SCHEDULE_CHANGE


@pytest.mark.django_db
def test_waitlisted_displaced_preserves_created_at_and_ignores_max_waitlist(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),
    )
    service = ServiceFactory(duration_minutes=30)

    # DayConfig with low max waitlist limit (e.g. 0)
    DayConfigFactory(weekday=3, is_open=True, max_appointments=1)

    orig_created = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=tz)
    start_at = datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )
    Appointment.objects.filter(id=appt.id).update(created_at=orig_created)

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)
    result = revalidate_worker(worker.id, now=now)

    assert result.waitlisted == 1
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
    assert appt.worker is None
    assert appt.created_at == orig_created


@pytest.mark.django_db
def test_fifo_between_displaced_appointments_competing_for_worker(tz):
    worker1 = WorkerFactory(full_name="Afectado")
    worker2 = WorkerFactory(full_name="Sustituto")
    target_date = datetime.date(2026, 10, 15)

    WorkScheduleFactory(
        worker=worker1,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),  # Lost afternoon
    )
    WorkScheduleFactory(
        worker=worker2,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),  # Can only take 1 appointment at 14:00
    )
    service = ServiceFactory(duration_minutes=30)
    slot_time = datetime.datetime.combine(target_date, datetime.time(14, 0), tzinfo=tz)

    created_older = datetime.datetime(2026, 10, 1, 9, 0, tzinfo=tz)
    created_newer = datetime.datetime(2026, 10, 1, 10, 0, tzinfo=tz)

    appt1 = AppointmentFactory(
        service=service,
        worker=worker1,
        date=target_date,
        start_at=slot_time,
        status=AppointmentStatus.CONFIRMED,
    )
    Appointment.objects.filter(id=appt1.id).update(created_at=created_older)

    appt2 = AppointmentFactory(
        service=service,
        worker=worker1,
        date=target_date,
        start_at=slot_time,
        status=AppointmentStatus.CONFIRMED,
    )
    Appointment.objects.filter(id=appt2.id).update(created_at=created_newer)

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)
    result = revalidate_worker(worker1.id, now=now)

    assert result.reassigned == 1
    assert result.waitlisted == 1

    appt1.refresh_from_db()
    appt2.refresh_from_db()

    # Older created_at won the reassignment
    assert appt1.status == AppointmentStatus.CONFIRMED
    assert appt1.worker == worker2

    # Newer created_at went to waitlist
    assert appt2.status == AppointmentStatus.WAITLISTED
    assert appt2.worker is None


@pytest.mark.django_db
def test_absence_exception_displaces_entire_day(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)

    appt1 = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )
    appt2 = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(14, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # Register absence
    ScheduleExceptionFactory(
        worker=worker,
        date=target_date,
        kind=ExceptionKind.ABSENCE,
        reason="Permiso médico",
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)
    result = revalidate_worker(worker.id, now=now)

    assert len(result.displaced) == 2
    appt1.refresh_from_db()
    appt2.refresh_from_db()
    assert appt1.status == AppointmentStatus.WAITLISTED
    assert appt2.status == AppointmentStatus.WAITLISTED


@pytest.mark.django_db
def test_past_or_in_progress_appointments_not_touched(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),  # Shortened
    )
    service = ServiceFactory(duration_minutes=30)

    # In progress / past appointment (start_at <= now)
    past_start = datetime.datetime.combine(target_date, datetime.time(14, 0), tzinfo=tz)
    appt_past = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=past_start,
        status=AppointmentStatus.CONFIRMED,
    )

    # Now is 14:15 (appointment already started)
    now = datetime.datetime.combine(target_date, datetime.time(14, 15), tzinfo=tz)
    result = revalidate_worker(worker.id, now=now)

    assert len(result.displaced) == 0
    appt_past.refresh_from_db()
    assert appt_past.status == AppointmentStatus.CONFIRMED
    assert appt_past.worker == worker


@pytest.mark.django_db
def test_expanding_shift_promotes_from_waitlist(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    schedule = WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),
    )
    service = ServiceFactory(duration_minutes=30)

    # Waitlisted appointment for 14:00
    appt_wait = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(14, 0), tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    # Expand shift to 17:00
    schedule.end_time = datetime.time(17, 0)
    schedule.save()

    # Worker has no confirmed appointments yet, but revalidate promotes waitlist on that date
    result = revalidate_worker(worker.id, now=now, dates=[target_date])

    assert result.promoted_from_waitlist == 1
    appt_wait.refresh_from_db()
    assert appt_wait.status == AppointmentStatus.CONFIRMED
    assert appt_wait.worker == worker


@pytest.mark.django_db
def test_unserviceable_waitlist_selector_and_over_quota(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),
    )
    service = ServiceFactory(duration_minutes=30)

    # Waitlisted appointment outside shift (e.g. 15:00)
    appt_unserv = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)
    unserviceable = list_unserviceable_waitlist(from_date=target_date, now=now)

    assert len(unserviceable) == 1
    assert unserviceable[0].id == appt_unserv.id


@pytest.mark.django_db
def test_revalidate_worker_idempotency(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)

    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    res1 = revalidate_worker(worker.id, now=now)
    assert len(res1.displaced) == 0

    res2 = revalidate_worker(worker.id, now=now)
    assert len(res2.displaced) == 0
    assert AppointmentEvent.objects.filter(appointment=appt).count() == 0
