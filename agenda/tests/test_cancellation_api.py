"""API tests for cancellation, rescheduling, completion, and appointments listing."""

import datetime
import uuid
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
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


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user():
    return User.objects.create_superuser(username="admin_api", password="password123")


@pytest.fixture
def normal_user():
    return User.objects.create_user(username="normal_api", password="password123")


@pytest.mark.django_db
def test_cancel_appointment_endpoint(api_client, tz):
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

    url = f"/api/v1/appointments/{appointment.id}/cancel/"
    payload = {"reason": "Imprevisto personal", "force": False}

    response = api_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(appointment.id)
    assert response.data["status"] == AppointmentStatus.CANCELLED


@pytest.mark.django_db
def test_cancel_non_existent_uuid_returns_404(api_client):
    random_id = uuid.uuid4()
    url = f"/api/v1/appointments/{random_id}/cancel/"
    response = api_client.post(url, {}, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["code"] == "appointment_not_found"


@pytest.mark.django_db
def test_cancel_force_permission_denied_for_non_staff(api_client, normal_user, tz):
    service = ServiceFactory()
    appointment = AppointmentFactory(service=service, status=AppointmentStatus.CONFIRMED)

    api_client.force_authenticate(user=normal_user)
    url = f"/api/v1/appointments/{appointment.id}/cancel/"
    payload = {"reason": "Forzar", "force": True}

    response = api_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_cancel_force_allowed_for_staff(api_client, staff_user, tz):
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    start_at = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz)

    appointment = AppointmentFactory(
        service=service,
        date=target_date,
        start_at=start_at,
        status=AppointmentStatus.CONFIRMED,
    )

    api_client.force_authenticate(user=staff_user)
    url = f"/api/v1/appointments/{appointment.id}/cancel/"
    payload = {"reason": "Emergencia médica", "force": True}

    response = api_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == AppointmentStatus.CANCELLED


@pytest.mark.django_db
def test_reschedule_endpoint(api_client, tz):
    worker = WorkerFactory()
    for day in range(5):
        WorkScheduleFactory(
            worker=worker,
            weekday=day,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
    service = ServiceFactory(duration_minutes=30)
    orig_date = datetime.date(2026, 10, 15)
    new_date = datetime.date(2026, 10, 16)

    orig_start = datetime.datetime.combine(orig_date, datetime.time(10, 0), tzinfo=tz)
    new_start = datetime.datetime.combine(new_date, datetime.time(11, 0), tzinfo=tz)

    appointment = AppointmentFactory(
        service=service,
        worker=worker,
        date=orig_date,
        start_at=orig_start,
        status=AppointmentStatus.CONFIRMED,
    )

    url = f"/api/v1/appointments/{appointment.id}/reschedule/"
    payload = {
        "start_at": new_start.isoformat(),
        "allow_waitlist": False,
        "force": False,
    }

    response = api_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["rescheduled_from"] == str(appointment.id)
    assert response.data["reschedule_count"] == 1


@pytest.mark.django_db
def test_staff_list_appointments_endpoint(api_client, staff_user, normal_user, tz):
    target_date = datetime.date(2026, 10, 15)
    service = ServiceFactory()
    AppointmentFactory(service=service, date=target_date, status=AppointmentStatus.CONFIRMED)

    # 1. Anonymous -> 401 / 403
    url = f"/api/v1/appointments/?date={target_date.isoformat()}"
    response = api_client.get(url)
    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    # 2. Non-staff -> 403
    api_client.force_authenticate(user=normal_user)
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

    # 3. Staff -> 200 paginated list
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert "results" in response.data
    assert len(response.data["results"]) >= 1


@pytest.mark.django_db
def test_complete_and_no_show_endpoints(api_client, staff_user, normal_user, tz):
    worker = WorkerFactory()
    service = ServiceFactory(duration_minutes=30)
    past_date = datetime.date.today() - datetime.timedelta(days=1)
    past_start = datetime.datetime.combine(past_date, datetime.time(10, 0), tzinfo=tz)

    appt1 = AppointmentFactory(
        service=service,
        worker=worker,
        date=past_date,
        start_at=past_start,
        status=AppointmentStatus.CONFIRMED,
    )
    appt2 = AppointmentFactory(
        service=service,
        worker=worker,
        date=past_date,
        start_at=past_start,
        status=AppointmentStatus.CONFIRMED,
    )

    complete_url = f"/api/v1/appointments/{appt1.id}/complete/"
    no_show_url = f"/api/v1/appointments/{appt2.id}/no-show/"

    # Non-staff -> 403
    api_client.force_authenticate(user=normal_user)
    assert api_client.post(complete_url).status_code == status.HTTP_403_FORBIDDEN
    assert api_client.post(no_show_url).status_code == status.HTTP_403_FORBIDDEN

    # Staff -> 200
    api_client.force_authenticate(user=staff_user)
    res_comp = api_client.post(complete_url)
    assert res_comp.status_code == status.HTTP_200_OK
    assert res_comp.data["status"] == AppointmentStatus.COMPLETED

    res_noshow = api_client.post(no_show_url)
    assert res_noshow.status_code == status.HTTP_200_OK
    assert res_noshow.data["status"] == AppointmentStatus.NO_SHOW
