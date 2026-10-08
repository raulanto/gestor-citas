"""Tests for appointment completion, no-show marking, and active appointment selectors."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from agenda.constants import AppointmentStatus, EventNote
from agenda.exceptions import InvalidStateTransition
from agenda.models import AppointmentEvent
from agenda.selectors.appointments import list_active_appointments
from agenda.services.completion import complete_appointment, mark_no_show
from agenda.tests.factories import AppointmentFactory, ServiceFactory, WorkerFactory

User = get_user_model()


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db
def test_complete_appointment_success(tz):
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

    # Completed after appointment start
    now = start_at + datetime.timedelta(minutes=30)
    staff_user = User.objects.create_superuser(username="admin_comp")

    updated = complete_appointment(appointment, actor=staff_user, now=now)

    assert updated.status == AppointmentStatus.COMPLETED
    event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
    assert event.from_status == AppointmentStatus.CONFIRMED
    assert event.to_status == AppointmentStatus.COMPLETED
    assert event.actor == staff_user
    assert event.note == EventNote.COMPLETED


@pytest.mark.django_db
def test_mark_no_show_success(tz):
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

    now = start_at + datetime.timedelta(minutes=15)
    staff_user = User.objects.create_superuser(username="admin_noshow")

    updated = mark_no_show(appointment, actor=staff_user, now=now)

    assert updated.status == AppointmentStatus.NO_SHOW
    event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
    assert event.from_status == AppointmentStatus.CONFIRMED
    assert event.to_status == AppointmentStatus.NO_SHOW
    assert event.actor == staff_user
    assert event.note == EventNote.NO_SHOW


@pytest.mark.django_db
def test_complete_or_no_show_before_start_raises_invalid_transition(tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    appointment = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    # 10 minutes before start_at
    now = start_at - datetime.timedelta(minutes=10)
    staff_user = User.objects.create_superuser(username="admin_early")

    with pytest.raises(InvalidStateTransition):
        complete_appointment(appointment, actor=staff_user, now=now)

    with pytest.raises(InvalidStateTransition):
        mark_no_show(appointment, actor=staff_user, now=now)


@pytest.mark.django_db
def test_complete_or_no_show_from_non_confirmed_state(tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    waitlisted_appt = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.WAITLISTED,
    )

    now = start_at + datetime.timedelta(minutes=30)
    staff_user = User.objects.create_superuser(username="admin_wait")

    with pytest.raises(InvalidStateTransition):
        complete_appointment(waitlisted_appt, actor=staff_user, now=now)

    with pytest.raises(InvalidStateTransition):
        mark_no_show(waitlisted_appt, actor=staff_user, now=now)


@pytest.mark.django_db
def test_list_active_appointments_selector(tz):
    target_date = datetime.date(2026, 10, 15)
    worker = WorkerFactory()
    service = ServiceFactory()

    appt_conf = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        status=AppointmentStatus.CONFIRMED,
    )
    appt_wait = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        status=AppointmentStatus.WAITLISTED,
    )
    appt_canc = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        status=AppointmentStatus.CANCELLED,
    )

    active = list_active_appointments(target_date)
    active_ids = [a.id for a in active]

    assert appt_conf.id in active_ids
    assert appt_wait.id in active_ids
    assert appt_canc.id not in active_ids
