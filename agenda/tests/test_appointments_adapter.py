"""Unit tests for AppointmentBusySlots adapter."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings

from agenda.adapters.appointments_busy import AppointmentBusySlots
from agenda.constants import AppointmentStatus
from agenda.services.capacity import Interval
from agenda.tests.factories import (
    AppointmentFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
)


@pytest.mark.django_db
def test_appointment_busy_slots_busy_intervals_and_active_count():
    tz = ZoneInfo(settings.TIME_ZONE)
    target_date = datetime.date(2026, 10, 12)

    w1 = WorkerFactory()
    w2 = WorkerFactory()
    svc = ServiceFactory(duration_minutes=30)
    req = RequesterFactory()

    # 1. w1 has a CONFIRMED appointment (occupies w1 time and consumes quota)
    AppointmentFactory(
        worker=w1,
        service=svc,
        requester=req,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # 2. w1 has a COMPLETED appointment (occupies w1 time and consumes quota)
    AppointmentFactory(
        worker=w1,
        service=svc,
        requester=req,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.COMPLETED,
    )

    # 3. A WAITLISTED appointment (no worker, consumes quota, does NOT occupy worker time)
    AppointmentFactory(
        worker=None,
        service=svc,
        requester=req,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 11, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 11, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # 4. A CANCELLED appointment (does NOT occupy time and does NOT consume quota)
    AppointmentFactory(
        worker=w2,
        service=svc,
        requester=req,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CANCELLED,
    )

    # 5. An appointment on a different date
    AppointmentFactory(
        worker=w1,
        service=svc,
        requester=req,
        date=datetime.date(2026, 10, 13),
        start_at=datetime.datetime(2026, 10, 13, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 13, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    adapter = AppointmentBusySlots()

    # Query busy intervals
    busy_map = adapter.busy_intervals(target_date)
    assert w1.id in busy_map
    assert len(busy_map[w1.id]) == 2
    assert Interval(datetime.time(9, 0), datetime.time(9, 30)) in busy_map[w1.id]
    assert Interval(datetime.time(10, 0), datetime.time(10, 30)) in busy_map[w1.id]
    assert w2.id not in busy_map  # cancelled appointment ignored

    # Query active count (CONFIRMED + COMPLETED + WAITLISTED = 3)
    count = adapter.active_count(target_date)
    assert count == 3
