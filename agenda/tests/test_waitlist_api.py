"""API tests for waitlist endpoints and serializers."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
from agenda.models import Appointment
from agenda.tests.factories import (
    AppointmentFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user():
    return User.objects.create_user(
        username="staff_user",
        email="staff@example.com",
        password="password123",
        is_staff=True,
    )


@pytest.fixture
def regular_user():
    return User.objects.create_user(
        username="regular_user",
        email="regular@example.com",
        password="password123",
        is_staff=False,
    )


@pytest.mark.django_db
def test_waitlist_api_permissions(api_client, staff_user, regular_user):
    """GET /api/v1/waitlist/ requires staff user (IsAdminUser)."""
    target_date = "2026-10-12"
    url = f"/api/v1/waitlist/?date={target_date}"

    # 1. Anonymous request -> 401 Unauthorized
    resp_anon = api_client.get(url)
    assert resp_anon.status_code in (401, 403)

    # 2. Authenticated non-staff request -> 403 Forbidden
    api_client.force_authenticate(user=regular_user)
    resp_regular = api_client.get(url)
    assert resp_regular.status_code == 403

    # 3. Staff request -> 200 OK
    api_client.force_authenticate(user=staff_user)
    resp_staff = api_client.get(url)
    assert resp_staff.status_code == 200


@pytest.mark.django_db
def test_waitlist_api_date_validation(api_client, staff_user):
    """GET /api/v1/waitlist/ validates required and correct date parameter."""
    api_client.force_authenticate(user=staff_user)

    # Missing date param
    resp_missing = api_client.get("/api/v1/waitlist/")
    assert resp_missing.status_code == 400
    assert resp_missing.json()["code"] == "INVALID_PARAMETERS"

    # Invalid date format
    resp_invalid = api_client.get("/api/v1/waitlist/?date=invalid-date")
    assert resp_invalid.status_code == 400
    assert resp_invalid.json()["code"] == "INVALID_PARAMETERS"


@pytest.mark.django_db
def test_waitlist_api_fifo_order_and_positions(api_client, staff_user, tz):
    """GET /api/v1/waitlist/ returns FIFO ordered appointments with calculated positions."""
    api_client.force_authenticate(user=staff_user)
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(name="Consulta General", duration_minutes=30)

    req1 = RequesterFactory(full_name="Ana Lopez")
    req2 = RequesterFactory(full_name="Carlos Gomez")

    start_1 = datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz)
    start_2 = datetime.datetime(2026, 10, 12, 11, 0, tzinfo=tz)

    appt1 = AppointmentFactory(
        requester=req1,
        service=service,
        worker=None,
        date=target_date,
        start_at=start_1,
        end_at=start_1 + datetime.timedelta(minutes=30),
        status=AppointmentStatus.WAITLISTED,
    )
    Appointment.objects.filter(id=appt1.id).update(
        created_at=datetime.datetime(2026, 10, 1, 9, 0, tzinfo=tz)
    )

    appt2 = AppointmentFactory(
        requester=req2,
        service=service,
        worker=None,
        date=target_date,
        start_at=start_2,
        end_at=start_2 + datetime.timedelta(minutes=30),
        status=AppointmentStatus.WAITLISTED,
    )
    Appointment.objects.filter(id=appt2.id).update(
        created_at=datetime.datetime(2026, 10, 1, 10, 0, tzinfo=tz)
    )

    # Also create a CONFIRMED appointment on the same date (should NOT be in waitlist)
    worker = WorkerFactory()
    AppointmentFactory(
        requester=req1,
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    resp = api_client.get(f"/api/v1/waitlist/?date={target_date.isoformat()}")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 2
    assert data[0]["id"] == str(appt1.id)
    assert data[0]["position"] == 1
    assert data[0]["requester_name"] == "Ana Lopez"
    assert data[0]["service"]["name"] == "Consulta General"

    assert data[1]["id"] == str(appt2.id)
    assert data[1]["position"] == 2
    assert data[1]["requester_name"] == "Carlos Gomez"


@pytest.mark.django_db
def test_waitlist_api_no_n_plus_one_queries(
    api_client, staff_user, django_assert_max_num_queries, tz
):
    """GET /api/v1/waitlist/ retrieves waitlisted items without N+1 query overhead."""
    api_client.force_authenticate(user=staff_user)
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)

    for i in range(5):
        req = RequesterFactory(full_name=f"User {i}")
        start_at = datetime.datetime(2026, 10, 12, 9 + i, 0, tzinfo=tz)
        AppointmentFactory(
            requester=req,
            service=service,
            worker=None,
            date=target_date,
            start_at=start_at,
            end_at=start_at + datetime.timedelta(minutes=30),
            status=AppointmentStatus.WAITLISTED,
        )

    # 1 query for user/auth, 1 query for waitlist + select_related
    with django_assert_max_num_queries(5):
        resp = api_client.get(f"/api/v1/waitlist/?date={target_date.isoformat()}")
        assert resp.status_code == 200
        assert len(resp.json()) == 5


@pytest.mark.django_db
def test_appointment_detail_waitlist_position(api_client, tz):
    """GET /api/v1/appointments/{id}/ includes waitlist_position (int or null)."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()

    # Confirmed appointment
    confirmed_appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 9, 30, tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # Waitlisted appointment
    waitlisted_appt = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # Check confirmed appointment detail
    resp_conf = api_client.get(f"/api/v1/appointments/{confirmed_appt.id}/")
    assert resp_conf.status_code == 200
    assert resp_conf.json()["waitlist_position"] is None

    # Check waitlisted appointment detail
    resp_wait = api_client.get(f"/api/v1/appointments/{waitlisted_appt.id}/")
    assert resp_wait.status_code == 200
    assert resp_wait.json()["waitlist_position"] == 1
