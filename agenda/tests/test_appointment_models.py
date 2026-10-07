"""Unit tests for Appointment and AppointmentEvent models."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from agenda.constants import AppointmentStatus
from agenda.models import Appointment, AppointmentEvent
from agenda.tests.factories import (
    AppointmentFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
)


@pytest.mark.django_db
def test_appointment_confirmed_creation():
    tz = ZoneInfo(settings.TIME_ZONE)
    start_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    end_at = datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz)

    appt = AppointmentFactory(
        status=AppointmentStatus.CONFIRMED,
        start_at=start_at,
        end_at=end_at,
        date=start_at.date(),
    )

    assert appt.id is not None
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker is not None


@pytest.mark.django_db
def test_appointment_waitlisted_creation():
    tz = ZoneInfo(settings.TIME_ZONE)
    start_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    end_at = datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz)

    appt = AppointmentFactory(
        status=AppointmentStatus.WAITLISTED,
        worker=None,
        start_at=start_at,
        end_at=end_at,
        date=start_at.date(),
    )

    assert appt.id is not None
    assert appt.status == AppointmentStatus.WAITLISTED
    assert appt.worker is None


@pytest.mark.django_db
def test_appointment_end_at_before_start_at_raises_validation_error():
    tz = ZoneInfo(settings.TIME_ZONE)
    start_at = datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz)
    end_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz)

    appt = Appointment(
        requester=RequesterFactory(),
        service=ServiceFactory(),
        worker=WorkerFactory(),
        date=start_at.date(),
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.CONFIRMED,
    )

    with pytest.raises(ValidationError):
        appt.clean()

    with pytest.raises(IntegrityError):
        appt.save()


@pytest.mark.django_db
def test_appointment_confirmed_without_worker_raises_validation_error():
    tz = ZoneInfo(settings.TIME_ZONE)
    start_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    end_at = datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz)

    appt = Appointment(
        requester=RequesterFactory(),
        service=ServiceFactory(),
        worker=None,
        date=start_at.date(),
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.CONFIRMED,
    )

    with pytest.raises(ValidationError):
        appt.clean()

    with pytest.raises(IntegrityError):
        appt.save()


@pytest.mark.django_db
def test_appointment_waitlisted_with_worker_raises_validation_error():
    tz = ZoneInfo(settings.TIME_ZONE)
    start_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    end_at = datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz)

    appt = Appointment(
        requester=RequesterFactory(),
        service=ServiceFactory(),
        worker=WorkerFactory(),
        date=start_at.date(),
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.WAITLISTED,
    )

    with pytest.raises(ValidationError):
        appt.clean()

    with pytest.raises(IntegrityError):
        appt.save()


@pytest.mark.django_db
def test_appointment_event_audit_creation():
    appt = AppointmentFactory()
    event = AppointmentEvent.objects.create(
        appointment=appt,
        from_status="",
        to_status=AppointmentStatus.CONFIRMED,
        worker=appt.worker,
        note="Cita creada en prueba",
    )

    assert event.id is not None
    assert event.appointment == appt
    assert event.to_status == AppointmentStatus.CONFIRMED
    assert "CONFIRMED" in str(event)
