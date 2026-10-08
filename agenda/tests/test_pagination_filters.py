"""Tests for pagination and filters across query endpoints."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
from agenda.models import Appointment
from agenda.tests.factories import (
    AppointmentFactory,
    ServiceFactory,
    WorkerFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo("America/Mexico_City")


@pytest.mark.django_db
def test_pagination_limit_clamping_and_validation(api_client: APIClient, staff_user, tz):
    """Limit > 100 is clamped to 100; invalid limit/offset returns 400."""
    api_client.force_authenticate(user=staff_user)
    target_date = datetime.date(2026, 10, 15)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()

    # Create 5 appointments
    for i in range(5):
        start_at = datetime.datetime(2026, 10, 15, 9 + i, 0, tzinfo=tz)
        AppointmentFactory(
            service=service,
            worker=worker,
            date=target_date,
            start_at=start_at,
            end_at=start_at + datetime.timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
        )

    # 1. Negative limit -> 400
    resp = api_client.get(f"/api/v1/appointments/?date={target_date}&limit=-5")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "INVALID_PARAMETERS"

    # 2. Non-numeric limit -> 400
    resp = api_client.get(f"/api/v1/appointments/?date={target_date}&limit=abc")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "INVALID_PARAMETERS"

    # 3. Limit > 100 clamped to 100
    resp = api_client.get(f"/api/v1/appointments/?date={target_date}&limit=500")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["count"] == 5
    assert len(resp.json()["results"]) == 5


@pytest.mark.django_db
def test_pagination_full_traversal(api_client: APIClient, staff_user, tz):
    """Iterate through pages without duplicates."""
    api_client.force_authenticate(user=staff_user)
    target_date = datetime.date(2026, 10, 15)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()

    created_ids = set()
    for i in range(12):
        start_at = datetime.datetime(2026, 10, 15, 8, 0, tzinfo=tz) + datetime.timedelta(
            minutes=30 * i
        )
        appt = AppointmentFactory(
            service=service,
            worker=worker,
            date=target_date,
            start_at=start_at,
            end_at=start_at + datetime.timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
        )
        created_ids.add(str(appt.id))

    # Page size 5
    collected_ids = []
    offset = 0
    while True:
        resp = api_client.get(f"/api/v1/appointments/?date={target_date}&limit=5&offset={offset}")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        results = data["results"]
        if not results:
            break
        for item in results:
            collected_ids.append(item["id"])
        offset += len(results)
        if offset >= data["count"]:
            break

    assert len(collected_ids) == 12
    assert set(collected_ids) == created_ids


@pytest.mark.django_db
def test_appointment_filters_combination(api_client: APIClient, staff_user, tz):
    """Filter by date range, multi-status, worker, and service."""
    api_client.force_authenticate(user=staff_user)
    service1 = ServiceFactory(duration_minutes=30)
    worker1 = WorkerFactory()
    worker2 = WorkerFactory()

    d1 = datetime.date(2026, 10, 10)
    d2 = datetime.date(2026, 10, 20)

    # 1. Matching item
    appt_match = AppointmentFactory(
        service=service1,
        worker=worker1,
        date=d1,
        start_at=datetime.datetime(2026, 10, 10, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 10, 10, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # 2. Different worker
    AppointmentFactory(
        service=service1,
        worker=worker2,
        date=d1,
        start_at=datetime.datetime(2026, 10, 10, 11, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 10, 11, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # 3. Different status (CANCELLED)
    AppointmentFactory(
        service=service1,
        worker=worker1,
        date=d1,
        start_at=datetime.datetime(2026, 10, 10, 12, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 10, 12, 30, tzinfo=tz),
        status=AppointmentStatus.CANCELLED,
    )

    # Multi-status query
    url = (
        f"/api/v1/appointments/?date_from={d1}&date_to={d2}"
        f"&worker={worker1.id}&service={service1.id}"
        f"&status=CONFIRMED&status=WAITLISTED"
    )
    resp = api_client.get(url)
    assert resp.status_code == status.HTTP_200_OK
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == str(appt_match.id)


@pytest.mark.django_db
def test_date_range_validation_max_92_days(api_client: APIClient, staff_user):
    """Date range > 92 days or date_to < date_from returns 400."""
    api_client.force_authenticate(user=staff_user)

    # 1. Range > 92 days
    d_from = "2026-01-01"
    d_to = "2026-05-01"  # 120 days
    resp = api_client.get(f"/api/v1/appointments/?date_from={d_from}&date_to={d_to}")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "INVALID_PARAMETERS"

    # 2. Inverted range
    resp = api_client.get("/api/v1/appointments/?date_from=2026-10-20&date_to=2026-10-10")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "INVALID_PARAMETERS"


@pytest.mark.django_db
def test_ordering_whitelist(api_client: APIClient, staff_user, tz):
    """Ordering with disallowed field returns 400; allowed orderings return 200 sorted."""
    api_client.force_authenticate(user=staff_user)
    target_date = datetime.date(2026, 10, 15)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()

    appt1 = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 15, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 15, 10, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )
    appt2 = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 15, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 15, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # 1. Disallowed ordering
    resp = api_client.get(f"/api/v1/appointments/?date={target_date}&ordering=id")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "INVALID_PARAMETERS"

    # 2. Descending start_at
    resp = api_client.get(f"/api/v1/appointments/?date={target_date}&ordering=-start_at")
    assert resp.status_code == status.HTTP_200_OK
    results = resp.json()["results"]
    assert results[0]["id"] == str(appt1.id)
    assert results[1]["id"] == str(appt2.id)


@pytest.mark.django_db
def test_waitlist_pagination_absolute_position(api_client: APIClient, staff_user, tz):
    """Waitlist entries on page 2 retain their absolute daily position."""
    api_client.force_authenticate(user=staff_user)
    target_date = datetime.date(2026, 10, 15)
    service = ServiceFactory(duration_minutes=30)

    for i in range(5):
        start_at = datetime.datetime(2026, 10, 15, 9 + i, 0, tzinfo=tz)
        appt = AppointmentFactory(
            service=service,
            worker=None,
            date=target_date,
            start_at=start_at,
            end_at=start_at + datetime.timedelta(minutes=30),
            status=AppointmentStatus.WAITLISTED,
        )
        Appointment.objects.filter(id=appt.id).update(
            created_at=datetime.datetime(2026, 10, 1, 9 + i, 0, tzinfo=tz)
        )

    # Page 1: limit 2, offset 0 -> positions 1, 2
    resp1 = api_client.get(f"/api/v1/waitlist/?date={target_date}&limit=2&offset=0")
    assert resp1.status_code == status.HTTP_200_OK
    page1 = resp1.json()["results"]
    assert len(page1) == 2
    assert page1[0]["position"] == 1
    assert page1[1]["position"] == 2

    # Page 2: limit 2, offset 2 -> positions 3, 4
    resp2 = api_client.get(f"/api/v1/waitlist/?date={target_date}&limit=2&offset=2")
    assert resp2.status_code == status.HTTP_200_OK
    page2 = resp2.json()["results"]
    assert len(page2) == 2
    assert page2[0]["position"] == 3
    assert page2[1]["position"] == 4


@pytest.mark.django_db
def test_appointment_list_constant_queries(
    api_client: APIClient, staff_user, django_assert_max_num_queries, tz
):
    """Listing appointments uses select_related / prefetch_related without N+1 query overhead."""
    api_client.force_authenticate(user=staff_user)
    target_date = datetime.date(2026, 10, 15)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()

    for i in range(10):
        start_at = datetime.datetime(2026, 10, 15, 8, 0, tzinfo=tz) + datetime.timedelta(
            minutes=30 * i
        )
        AppointmentFactory(
            service=service,
            worker=worker,
            date=target_date,
            start_at=start_at,
            end_at=start_at + datetime.timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
        )

    # Constant number of queries per page
    with django_assert_max_num_queries(8):
        resp = api_client.get(f"/api/v1/appointments/?date={target_date}&limit=10")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()["results"]) == 10
