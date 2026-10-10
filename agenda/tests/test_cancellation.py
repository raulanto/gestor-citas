"""Tests for appointment cancellation domain logic."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from agenda.constants import AppointmentStatus
from agenda.exceptions import CancellationNotAllowed, InvalidStateTransition
from agenda.models import AppointmentEvent, DayConfig
from agenda.services.cancellation import cancel_appointment, cancel_appointments_for_day
from agenda.tests.factories import (
    AppointmentFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)

User = get_user_model()


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db
def test_cancel_confirmed_appointment_success(tz):
    worker = WorkerFactory()
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)
    end_at = datetime.datetime.combine(target_date, datetime.time(10, 30), tzinfo=tz)

    appointment = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.CONFIRMED,
    )

    now = start_at - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)
    user = User.objects.create_user(username="test_canceller")

    result = cancel_appointment(
        appointment,
        reason="No podré asistir",
        actor=user,
        now=now,
    )

    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CANCELLED
    assert result.status == AppointmentStatus.CANCELLED

    # Check event
    event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
    assert event.from_status == AppointmentStatus.CONFIRMED
    assert event.to_status == AppointmentStatus.CANCELLED
    assert event.actor == user
    assert "No podré asistir" in event.note


@pytest.mark.django_db
def test_cancel_confirmed_promotes_waitlisted_in_same_transaction(tz):
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=3,  # Thursday
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)  # Thursday
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)
    end_at = datetime.datetime.combine(target_date, datetime.time(10, 30), tzinfo=tz)

    # 1. Confirmed appointment holding the worker
    confirmed_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.CONFIRMED,
    )

    # 2. Waitlisted appointment waiting for same slot
    waitlisted_appt = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.WAITLISTED,
    )

    now = start_at - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 2)

    # Cancel confirmed appointment
    cancel_appointment(confirmed_appt, reason="Cancelación", now=now)

    confirmed_appt.refresh_from_db()
    assert confirmed_appt.status == AppointmentStatus.CANCELLED

    # Waitlisted appointment should have been automatically promoted to CONFIRMED
    waitlisted_appt.refresh_from_db()
    assert waitlisted_appt.status == AppointmentStatus.CONFIRMED
    assert waitlisted_appt.worker == worker


@pytest.mark.django_db
def test_cancellation_anticipation_exact_boundaries(tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    appointment = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    # Exact boundary: now == start_at - CANCEL_MIN_HOURS -> Allowed
    exact_deadline = start_at - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS)
    cancel_appointment(appointment, reason="En el límite", now=exact_deadline)

    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CANCELLED

    # 1 second past deadline for a new appointment -> Rejected
    appt2 = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )
    one_sec_past = exact_deadline + datetime.timedelta(seconds=1)
    with pytest.raises(CancellationNotAllowed) as exc_info:
        cancel_appointment(appt2, reason="Tarde", now=one_sec_past)

    assert exc_info.value.http_status == 409
    appt2.refresh_from_db()
    assert appt2.status == AppointmentStatus.CONFIRMED


@pytest.mark.django_db
def test_waitlist_cancellation_anytime_before_start_at(tz):
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

    # 5 minutes before start_at (even within CANCEL_MIN_HOURS window) -> Allowed
    now = start_at - datetime.timedelta(minutes=5)
    cancel_appointment(waitlisted_appt, reason="No deseo esperar más", now=now)

    waitlisted_appt.refresh_from_db()
    assert waitlisted_appt.status == AppointmentStatus.CANCELLED


@pytest.mark.django_db
def test_cancellation_past_or_started_appointment_rejected_even_with_force(tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    staff_user = User.objects.create_superuser(username="admin_user")

    # 1. Confirmed appointment already started: start_at == now
    confirmed_appt = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )
    with pytest.raises(CancellationNotAllowed):
        cancel_appointment(confirmed_appt, force=True, actor=staff_user, now=start_at)

    # 2. Waitlisted appointment past: now > start_at
    waitlisted_appt = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.WAITLISTED,
    )
    past_now = start_at + datetime.timedelta(minutes=10)
    with pytest.raises(CancellationNotAllowed):
        cancel_appointment(waitlisted_appt, force=True, actor=staff_user, now=past_now)


@pytest.mark.django_db
def test_cancellation_idempotency_and_terminal_states(tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    now = start_at - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS + 1)
    appointment = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    # First cancel
    cancel_appointment(appointment, reason="Primera", now=now)
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CANCELLED
    events_count = AppointmentEvent.objects.filter(appointment=appointment).count()

    # Second cancel -> Idempotent success without new event
    result = cancel_appointment(appointment, reason="Segunda", now=now)
    assert result.status == AppointmentStatus.CANCELLED
    assert AppointmentEvent.objects.filter(appointment=appointment).count() == events_count

    # From other terminal state -> InvalidStateTransition
    completed_appt = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.COMPLETED,
    )
    with pytest.raises(InvalidStateTransition):
        cancel_appointment(completed_appt, reason="Intento", now=now)


@pytest.mark.django_db
def test_staff_force_bypasses_anticipation_window(tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    # Less than CANCEL_MIN_HOURS before start_at
    now = start_at - datetime.timedelta(hours=settings.CANCEL_MIN_HOURS - 1)
    appointment = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    staff_user = User.objects.create_superuser(username="admin_force")
    cancel_appointment(
        appointment,
        reason="Cancelación médica urgente",
        actor=staff_user,
        force=True,
        now=now,
    )

    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CANCELLED

    event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
    assert "forzada" in event.note or "urgente" in event.note


@pytest.mark.django_db
def test_cancel_appointments_for_day_staff_service(tz):
    worker = WorkerFactory()
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)

    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)

    # Active future appointments
    appt1 = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(9, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )
    appt2 = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # Already cancelled / terminal appointment
    appt3 = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(11, 0), tzinfo=tz),
        status=AppointmentStatus.CANCELLED,
    )

    staff_user = User.objects.create_superuser(username="manager")
    count = cancel_appointments_for_day(
        target_date,
        reason="Cierre de sucursal por mantenimiento",
        actor=staff_user,
        now=now,
    )

    assert count == 2
    appt1.refresh_from_db()
    appt2.refresh_from_db()
    appt3.refresh_from_db()

    assert appt1.status == AppointmentStatus.CANCELLED
    assert appt2.status == AppointmentStatus.CANCELLED
    assert appt3.status == AppointmentStatus.CANCELLED

    # Check events recorded
    assert AppointmentEvent.objects.filter(
        appointment=appt1, to_status=AppointmentStatus.CANCELLED
    ).exists()
    assert AppointmentEvent.objects.filter(
        appointment=appt2, to_status=AppointmentStatus.CANCELLED
    ).exists()


@pytest.mark.django_db
def test_cancellation_respects_day_config_custom_cancel_min_hours(tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(18, 0), tzinfo=tz)

    DayConfig.objects.create(
        date=target_date,
        is_open=True,
        cancel_min_hours=8,
    )

    appointment = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    # 6 hours before start_at is allowed under default (4h), but fails with 8h
    now_6h_before = start_at - datetime.timedelta(hours=6)
    with pytest.raises(CancellationNotAllowed):
        cancel_appointment(appointment, now=now_6h_before)

    # 10 hours before start_at succeeds
    now_10h_before = start_at - datetime.timedelta(hours=10)
    cancelled = cancel_appointment(appointment, now=now_10h_before)
    assert cancelled.status == AppointmentStatus.CANCELLED
