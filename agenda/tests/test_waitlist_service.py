"""Tests for waitlist processing service."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings

from agenda.constants import AppointmentStatus, EventNote, QUOTA_STATUSES
from agenda.models import Appointment, AppointmentEvent, ExceptionKind, Weekday
from agenda.services.waitlist import process_waitlist, process_waitlist_all
from agenda.tests.factories import (
    AppointmentEventFactory,
    AppointmentFactory,
    DayConfigFactory,
    RequesterFactory,
    ScheduleExceptionFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.fixture
def target_date():
    # 2026-10-12 is a Monday
    return datetime.date(2026, 10, 12)


@pytest.fixture
def base_setup(target_date, tz):
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
    return service, worker


@pytest.mark.django_db
def test_waitlist_promotion_when_worker_freed(base_setup, target_date, tz):
    """A waitlisted appointment is promoted to CONFIRMED with worker and event when worker is freed."""
    service, worker = base_setup
    start_at = datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz)
    end_at = start_at + datetime.timedelta(minutes=30)
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    # Initial blocking appointment (simulating another appointment that was cancelled)
    blocking_appt = AppointmentFactory(
        worker=worker,
        service=service,
        date=target_date,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.CANCELLED,  # Liberado
    )

    # Waitlisted appointment for the same slot
    waitlisted_appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.WAITLISTED,
    )
    AppointmentEventFactory(
        appointment=waitlisted_appt,
        from_status="",
        to_status=AppointmentStatus.WAITLISTED,
        worker=None,
    )

    res = process_waitlist(target_date, now=now_dt)

    assert len(res.assigned) == 1
    assert res.remaining == 0
    assert res.assigned[0].id == waitlisted_appt.id

    waitlisted_appt.refresh_from_db()
    assert waitlisted_appt.status == AppointmentStatus.CONFIRMED
    assert waitlisted_appt.worker == worker

    event = AppointmentEvent.objects.filter(
        appointment=waitlisted_appt,
        to_status=AppointmentStatus.CONFIRMED,
    ).first()
    assert event is not None
    assert event.from_status == AppointmentStatus.WAITLISTED
    assert event.worker == worker
    assert event.note == EventNote.WAITLIST_ASSIGNED


@pytest.mark.django_db
def test_waitlist_fifo_order(base_setup, target_date, tz):
    """Two appointments competing for the same slot: older created_at gets assigned, newer remains waitlisted."""
    service, worker = base_setup
    start_at = datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz)
    end_at = start_at + datetime.timedelta(minutes=30)
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    created_1 = datetime.datetime(2026, 10, 1, 10, 0, tzinfo=tz)
    created_2 = datetime.datetime(2026, 10, 1, 11, 0, tzinfo=tz)

    appt_first = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.WAITLISTED,
    )
    Appointment.objects.filter(id=appt_first.id).update(created_at=created_1)

    appt_second = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.WAITLISTED,
    )
    Appointment.objects.filter(id=appt_second.id).update(created_at=created_2)

    res = process_waitlist(target_date, now=now_dt)

    assert len(res.assigned) == 1
    assert res.remaining == 1
    assert res.assigned[0].id == appt_first.id

    appt_first.refresh_from_db()
    appt_second.refresh_from_db()

    assert appt_first.status == AppointmentStatus.CONFIRMED
    assert appt_first.worker == worker
    assert appt_second.status == AppointmentStatus.WAITLISTED
    assert appt_second.worker is None


@pytest.mark.django_db
def test_waitlist_no_head_of_line_blocking(base_setup, target_date, tz):
    """If the first waitlisted appointment cannot be served, the second for another slot is still assigned."""
    service, worker = base_setup
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    # 10:00 is occupied by an active appointment
    slot_1_start = datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz)
    slot_1_end = slot_1_start + datetime.timedelta(minutes=30)
    AppointmentFactory(
        worker=worker,
        service=service,
        date=target_date,
        start_at=slot_1_start,
        end_at=slot_1_end,
        status=AppointmentStatus.CONFIRMED,
    )

    # 11:00 is free
    slot_2_start = datetime.datetime(2026, 10, 12, 11, 0, tzinfo=tz)
    slot_2_end = slot_2_start + datetime.timedelta(minutes=30)

    # First in FIFO queue (requested 10:00 - still occupied)
    appt_blocked = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=slot_1_start,
        end_at=slot_1_end,
        status=AppointmentStatus.WAITLISTED,
    )
    Appointment.objects.filter(id=appt_blocked.id).update(
        created_at=datetime.datetime(2026, 10, 1, 8, 0, tzinfo=tz)
    )

    # Second in FIFO queue (requested 11:00 - free)
    appt_free = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=slot_2_start,
        end_at=slot_2_end,
        status=AppointmentStatus.WAITLISTED,
    )
    Appointment.objects.filter(id=appt_free.id).update(
        created_at=datetime.datetime(2026, 10, 1, 9, 0, tzinfo=tz)
    )

    res = process_waitlist(target_date, now=now_dt)

    assert len(res.assigned) == 1
    assert res.remaining == 1
    assert res.assigned[0].id == appt_free.id

    appt_blocked.refresh_from_db()
    appt_free.refresh_from_db()

    assert appt_blocked.status == AppointmentStatus.WAITLISTED
    assert appt_free.status == AppointmentStatus.CONFIRMED
    assert appt_free.worker == worker


@pytest.mark.django_db
def test_waitlist_multiple_workers_load_balancing(target_date, tz):
    """Assigns across multiple free workers respecting least loaded worker rule."""
    service = ServiceFactory(duration_minutes=30)
    w1 = WorkerFactory()
    w2 = WorkerFactory()

    for w in (w1, w2):
        WorkScheduleFactory(
            worker=w,
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

    # Worker 1 already has 1 appointment at 09:00
    AppointmentFactory(
        worker=w1,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # Waitlisted appointment for 10:00 (both workers free, but w2 has load 0 vs w1 load 1)
    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    res = process_waitlist(target_date, now=now_dt)

    assert len(res.assigned) == 1
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == w2  # w2 picked because load=0 < load=1


@pytest.mark.django_db
def test_waitlist_closed_day_and_reopen(base_setup, target_date, tz):
    """A closed day does not assign waitlist; reopening the day and running process_waitlist assigns it."""
    service, worker = base_setup
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    # Specific date closed
    day_cfg = DayConfigFactory(
        date=target_date,
        is_open=False,
        max_appointments=20,
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # Processing on closed day
    res_closed = process_waitlist(target_date, now=now_dt)
    assert len(res_closed.assigned) == 0
    assert res_closed.remaining == 1

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED

    # Reopen day
    day_cfg.is_open = True
    day_cfg.save()

    res_open = process_waitlist(target_date, now=now_dt)
    assert len(res_open.assigned) == 1
    assert res_open.remaining == 0

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == worker


@pytest.mark.django_db
def test_waitlist_new_worker_activated(target_date, tz):
    """Adding a new worker with covering schedule assigns pending waitlisted appointment."""
    service = ServiceFactory(duration_minutes=30)
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # Currently no workers -> 0 assigned
    res_before = process_waitlist(target_date, now=now_dt)
    assert len(res_before.assigned) == 0

    # Add worker and schedule
    new_worker = WorkerFactory()
    WorkScheduleFactory(
        worker=new_worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )

    res_after = process_waitlist(target_date, now=now_dt)
    assert len(res_after.assigned) == 1
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == new_worker


@pytest.mark.django_db
def test_waitlist_absence_deleted(base_setup, target_date, tz):
    """Deleting an absence allows waitlisted appointment to be assigned to the worker."""
    service, worker = base_setup
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    # Worker has an absence on this date
    absence = ScheduleExceptionFactory(
        worker=worker,
        date=target_date,
        kind=ExceptionKind.ABSENCE,
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    res_before = process_waitlist(target_date, now=now_dt)
    assert len(res_before.assigned) == 0

    # Delete absence
    absence.delete()

    res_after = process_waitlist(target_date, now=now_dt)
    assert len(res_after.assigned) == 1
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == worker


@pytest.mark.django_db
def test_waitlist_schedule_changed_no_longer_covers(base_setup, target_date, tz):
    """If the worker's shift changed and no longer covers the slot, appointment remains waitlisted."""
    service, worker = base_setup
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    # Shift changed to 14:00 - 18:00
    WorkSchedule.objects.filter(worker=worker, weekday=Weekday.MONDAY).update(
        start_time=datetime.time(14, 0),
        end_time=datetime.time(18, 0),
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    res = process_waitlist(target_date, now=now_dt)
    assert len(res.assigned) == 0
    assert res.remaining == 1

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
    assert appt.worker is None


@pytest.mark.django_db
def test_waitlist_active_count_remains_constant(base_setup, target_date, tz):
    """Quota consumption (QUOTA_STATUSES) does not change before vs after promotion."""
    service, worker = base_setup
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    count_before = Appointment.objects.filter(
        date=target_date,
        status__in=QUOTA_STATUSES,
    ).count()
    assert count_before == 1

    process_waitlist(target_date, now=now_dt)

    count_after = Appointment.objects.filter(
        date=target_date,
        status__in=QUOTA_STATUSES,
    ).count()
    assert count_after == 1


@pytest.mark.django_db
def test_waitlist_idempotency(base_setup, target_date, tz):
    """Running process_waitlist twice generates no duplicate assignments or events."""
    service, worker = base_setup
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    res1 = process_waitlist(target_date, now=now_dt)
    assert len(res1.assigned) == 1
    events_count_1 = AppointmentEvent.objects.filter(appointment=appt).count()

    res2 = process_waitlist(target_date, now=now_dt)
    assert len(res2.assigned) == 0
    assert res2.remaining == 0
    events_count_2 = AppointmentEvent.objects.filter(appointment=appt).count()

    assert events_count_1 == events_count_2


@pytest.mark.django_db
def test_process_waitlist_all(target_date, tz):
    """process_waitlist_all processes multiple dates with waitlisted appointments."""
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    for wd in (Weekday.MONDAY, Weekday.TUESDAY):
        WorkScheduleFactory(
            worker=worker,
            weekday=wd,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        DayConfigFactory(
            weekday=wd,
            is_open=True,
            max_appointments=20,
        )

    date1 = datetime.date(2026, 10, 12)  # Monday
    date2 = datetime.date(2026, 10, 13)  # Tuesday
    now_dt = datetime.datetime(2026, 10, 12, 8, 0, tzinfo=tz)

    appt1 = AppointmentFactory(
        worker=None,
        service=service,
        date=date1,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )
    appt2 = AppointmentFactory(
        worker=None,
        service=service,
        date=date2,
        start_at=datetime.datetime(2026, 10, 13, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 13, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    results = process_waitlist_all(now=now_dt)
    assert len(results) == 2
    assert sum(len(r.assigned) for r in results) == 2

    appt1.refresh_from_db()
    appt2.refresh_from_db()
    assert appt1.status == AppointmentStatus.CONFIRMED
    assert appt2.status == AppointmentStatus.CONFIRMED
