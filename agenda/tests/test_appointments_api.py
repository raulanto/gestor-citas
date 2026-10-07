"""Integration tests for Appointment API endpoints."""

import datetime
import uuid
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
from agenda.models import DayConfig, Weekday
from agenda.tests.factories import (
    DayConfigFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def setup_api_env():
    tz = ZoneInfo(settings.TIME_ZONE)
    target_date = datetime.date(2026, 10, 12)  # Monday

    service = ServiceFactory(id=1, name="Consulta General", duration_minutes=30)
    w1 = WorkerFactory(id=1, full_name="Dra. Ana López")
    w2 = WorkerFactory(id=2, full_name="Dr. Carlos Ruiz")

    for w in (w1, w2):
        WorkScheduleFactory(
            worker=w,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            break_start=None,
            break_end=None,
        )

    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )

    return {
        "tz": tz,
        "date": target_date,
        "service": service,
        "workers": (w1, w2),
    }


@pytest.mark.django_db
def test_post_appointment_confirmed_success(api_client, setup_api_env):
    payload = {
        "requester": {
            "full_name": "Ana Pérez",
            "phone": "993 123 4567",
            "email": "ana@example.com",
        },
        "service": 1,
        "start_at": "2026-10-12T09:00:00-06:00",
    }

    response = api_client.post("/api/v1/appointments/", payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "id" in data
    assert data["status"] == AppointmentStatus.CONFIRMED
    assert data["service"]["id"] == 1
    assert data["service"]["name"] == "Consulta General"
    assert data["service"]["duration_minutes"] == 30
    assert data["date"] == "2026-10-12"
    assert data["start_at"] == "2026-10-12T09:00:00-06:00"
    assert data["end_at"] == "2026-10-12T09:30:00-06:00"
    assert data["requester"]["full_name"] == "Ana Pérez"
    assert data["requester"]["phone"] == "9931234567"
    assert data["worker_name"] == "Dra. Ana López"


@pytest.mark.django_db
def test_post_appointment_waitlisted_success(api_client, setup_api_env):
    # Book slots for both workers first
    api_client.post(
        "/api/v1/appointments/",
        {
            "requester": {"full_name": "Req 1", "phone": "5551111111"},
            "service": 1,
            "start_at": "2026-10-12T09:00:00-06:00",
        },
        format="json",
    )
    api_client.post(
        "/api/v1/appointments/",
        {
            "requester": {"full_name": "Req 2", "phone": "5552222222"},
            "service": 1,
            "start_at": "2026-10-12T09:00:00-06:00",
        },
        format="json",
    )

    # 3rd booking for the same slot -> Waitlisted
    response = api_client.post(
        "/api/v1/appointments/",
        {
            "requester": {"full_name": "Req 3", "phone": "5553333333"},
            "service": 1,
            "start_at": "2026-10-12T09:00:00-06:00",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["status"] == AppointmentStatus.WAITLISTED
    assert data["worker_name"] is None


@pytest.mark.django_db
def test_post_appointment_invalid_body(api_client):
    response = api_client.post(
        "/api/v1/appointments/",
        {"service": 1},  # missing requester and start_at
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["code"] == "INVALID_PARAMETERS"


@pytest.mark.django_db
def test_post_appointment_quota_exceeded(api_client, setup_api_env):
    DayConfig.objects.filter(weekday=Weekday.MONDAY).update(max_appointments=1)

    # First booking uses the single quota slot
    api_client.post(
        "/api/v1/appointments/",
        {
            "requester": {"full_name": "Req 1", "phone": "5551111111"},
            "service": 1,
            "start_at": "2026-10-12T09:00:00-06:00",
        },
        format="json",
    )

    # Second booking -> QuotaExceeded (409 Conflict)
    response = api_client.post(
        "/api/v1/appointments/",
        {
            "requester": {"full_name": "Req 2", "phone": "5552222222"},
            "service": 1,
            "start_at": "2026-10-12T09:30:00-06:00",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    data = response.json()
    assert data["code"] == "quota_exceeded"


@pytest.mark.django_db
def test_get_appointment_detail_and_not_found(api_client, setup_api_env):
    post_res = api_client.post(
        "/api/v1/appointments/",
        {
            "requester": {"full_name": "Ana Pérez", "phone": "993 123 4567"},
            "service": 1,
            "start_at": "2026-10-12T09:00:00-06:00",
        },
        format="json",
    )
    appt_id = post_res.json()["id"]

    # 200 OK
    get_res = api_client.get(f"/api/v1/appointments/{appt_id}/")
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["id"] == appt_id

    # 404 NOT FOUND
    random_id = uuid.uuid4()
    not_found_res = api_client.get(f"/api/v1/appointments/{random_id}/")
    assert not_found_res.status_code == status.HTTP_404_NOT_FOUND
    assert not_found_res.json()["code"] == "appointment_not_found"


@pytest.mark.django_db
def test_availability_endpoint_reflects_booked_appointments(api_client, setup_api_env):
    # Query availability before booking
    res_before = api_client.get("/api/v1/availability/?date=2026-10-12&service=1")
    assert res_before.status_code == status.HTTP_200_OK
    data_before = res_before.json()
    slot_0900_before = next(
        s for s in data_before["slots"] if s["start"] == "2026-10-12T09:00:00-06:00"
    )
    assert slot_0900_before["free_workers"] == 2
    assert data_before["remaining_quota"] == 20

    # Book one slot at 09:00
    api_client.post(
        "/api/v1/appointments/",
        {
            "requester": {"full_name": "Req 1", "phone": "5551111111"},
            "service": 1,
            "start_at": "2026-10-12T09:00:00-06:00",
        },
        format="json",
    )

    # Query availability after booking
    res_after = api_client.get("/api/v1/availability/?date=2026-10-12&service=1")
    assert res_after.status_code == status.HTTP_200_OK
    data_after = res_after.json()
    slot_0900_after = next(
        s for s in data_after["slots"] if s["start"] == "2026-10-12T09:00:00-06:00"
    )
    assert slot_0900_after["free_workers"] == 1
    assert data_after["remaining_quota"] == 19
