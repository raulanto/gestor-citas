"""Tests for waitlist expiration service."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings

from agenda.constants import AppointmentStatus, EventNote, QUOTA_STATUSES
from agenda.models import Appointment, AppointmentEvent
from agenda.services.waitlist import expire_waitlist
from agenda.tests.factories import (
    AppointmentEventFactory,
    AppointmentFactory,
    ServiceFactory,
    WorkerFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.mark.django_db
def test_expire_past_waitlisted_appointments(tz):
    """Past waitlisted appointments (start_at <= now) are marked EXPIRED with event, future waitlisted remain."""
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    now_dt = datetime.datetime(2026, 10, 12, 12, 0, tzinfo=tz)

    # Past waitlisted appointment
    past_appt = AppointmentFactory(
        worker=None,
        service=service,
        date=datetime.date(2026, 10, 12),
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )
    AppointmentEventFactory(
        appointment=past_appt,
        from_status="",
        to_status=AppointmentStatus.WAITLISTED,
        worker=None,
    )

    # Future waitlisted appointment
    future_appt = AppointmentFactory(
        worker=None,
        service=service,
        date=datetime.date(2026, 10, 12),
        start_at=datetime.datetime(2026, 10, 12, 14, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 14, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # Past confirmed appointment (must NOT be expired)
    past_confirmed = AppointmentFactory(
        worker=worker,
        service=service,
        date=datetime.date(2026, 10, 12),
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # Active quota count before expiration
    active_before = Appointment.objects.filter(
        date=datetime.date(2026, 10, 12),
        status__in=QUOTA_STATUSES,
    ).count()
    assert active_before == 3  # past_appt (WAITLISTED), future_appt (WAITLISTED), past_confirmed (CONFIRMED)

    expired_count = expire_waitlist(now=now_dt)
    assert expired_count == 1

    past_appt.refresh_from_db()
    future_appt.refresh_from_db()
    past_confirmed.refresh_from_db()

    assert past_appt.status == AppointmentStatus.EXPIRED
    assert future_appt.status == AppointmentStatus.WAITLISTED
    assert past_confirmed.status == AppointmentStatus.CONFIRMED

    # Check event created for expired appointment
    event = AppointmentEvent.objects.filter(
        appointment=past_appt,
        to_status=AppointmentStatus.EXPIRED,
    ).first()
    assert event is not None
    assert event.from_status == AppointmentStatus.WAITLISTED
    assert event.note == EventNote.WAITLIST_EXPIRED

    # Active quota count decreases because EXPIRED is not in QUOTA_STATUSES
    active_after = Appointment.objects.filter(
        date=datetime.date(2026, 10, 12),
        status__in=QUOTA_STATUSES,
    ).count()
    assert active_after == 2


@pytest.mark.django_db
def test_expire_waitlist_idempotency(tz):
    """Running expire_waitlist multiple times does not recreate events or count."""
    service = ServiceFactory(duration_minutes=30)
    now_dt = datetime.datetime(2026, 10, 12, 12, 0, tzinfo=tz)

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=datetime.date(2026, 10, 12),
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    count1 = expire_waitlist(now=now_dt)
    assert count1 == 1

    count2 = expire_waitlist(now=now_dt)
    assert count2 == 0

    events = AppointmentEvent.objects.filter(appointment=appt, to_status=AppointmentStatus.EXPIRED)
    assert events.count() == 1
