"""Tests for GET /api/v1/me/agenda/ endpoint."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
from agenda.tests.factories import (
    AppointmentFactory,
    RequesterFactory,
    WorkerFactory,
    WorkerUserFactory,
)


@pytest.mark.django_db
class TestWorkerAgendaEndpoint:
    """Test worker agenda querying, role permissions, and filtering."""

    def test_worker_queries_own_agenda(self, auth_client_for_user):
        worker_user = WorkerUserFactory()
        worker = worker_user.worker_profile
        client = auth_client_for_user(worker_user)

        target_date = datetime.date(2026, 10, 20)
        tz = ZoneInfo(settings.TIME_ZONE)

        # Confirmed appointment for today
        r1 = RequesterFactory(full_name="Cliente Uno", phone="5551111111")
        appt1 = AppointmentFactory(
            worker=worker,
            date=target_date,
            start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
            status=AppointmentStatus.CONFIRMED,
            requester=r1,
        )

        # Another confirmed appointment later in the day
        r2 = RequesterFactory(full_name="Cliente Dos", phone="5552222222")
        appt2 = AppointmentFactory(
            worker=worker,
            date=target_date,
            start_at=datetime.datetime.combine(target_date, datetime.time(11, 0), tzinfo=tz),
            status=AppointmentStatus.CONFIRMED,
            requester=r2,
        )

        # Cancelled appointment (should be excluded)
        AppointmentFactory(
            worker=worker,
            date=target_date,
            status=AppointmentStatus.CANCELLED,
        )

        # Appointment for another worker (should be excluded)
        other_worker = WorkerFactory()
        AppointmentFactory(
            worker=other_worker,
            date=target_date,
            status=AppointmentStatus.CONFIRMED,
        )

        response = client.get(f"/api/v1/me/agenda/?date={target_date.isoformat()}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2

        assert data[0]["id"] == str(appt1.id)
        assert data[0]["requester"]["full_name"] == "Cliente Uno"
        assert data[0]["requester"]["phone"] == "5551111111"
        assert "email" not in data[0]["requester"]

        assert data[1]["id"] == str(appt2.id)

    def test_worker_cannot_query_other_worker_agenda(self, auth_client_for_user):
        worker_user = WorkerUserFactory()
        client = auth_client_for_user(worker_user)
        other_worker = WorkerFactory()

        response = client.get(f"/api/v1/me/agenda/?date=2026-10-20&worker_id={other_worker.id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "FORBIDDEN"

    def test_staff_queries_worker_agenda_with_worker_id(self, staff_client: APIClient):
        worker = WorkerFactory(full_name="Dr. House")
        target_date = datetime.date(2026, 10, 20)
        tz = ZoneInfo(settings.TIME_ZONE)

        appt = AppointmentFactory(
            worker=worker,
            date=target_date,
            start_at=datetime.datetime.combine(target_date, datetime.time(9, 0), tzinfo=tz),
            status=AppointmentStatus.CONFIRMED,
        )

        response = staff_client.get(
            f"/api/v1/me/agenda/?date={target_date.isoformat()}&worker_id={worker.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(appt.id)

    def test_staff_missing_worker_id_returns_400(self, staff_client: APIClient):
        response = staff_client.get("/api/v1/me/agenda/?date=2026-10-20")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "INVALID_PARAMETERS"

    def test_staff_nonexistent_worker_returns_404(self, staff_client: APIClient):
        response = staff_client.get("/api/v1/me/agenda/?date=2026-10-20&worker_id=99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"].lower() == "worker_not_found"

    def test_anonymous_access_returns_401(self, api_client: APIClient):
        response = api_client.get("/api/v1/me/agenda/?date=2026-10-20")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["code"] == "NOT_AUTHENTICATED"

    def test_user_without_role_returns_403(self, auth_client_for_user, plain_user):
        client = auth_client_for_user(plain_user)
        response = client.get("/api/v1/me/agenda/?date=2026-10-20")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_or_invalid_date_param(self, worker_client: APIClient):
        # Missing date
        resp1 = worker_client.get("/api/v1/me/agenda/")
        assert resp1.status_code == status.HTTP_400_BAD_REQUEST
        assert resp1.json()["code"] == "INVALID_PARAMETERS"

        # Invalid date format
        resp2 = worker_client.get("/api/v1/me/agenda/?date=invalid-date")
        assert resp2.status_code == status.HTTP_400_BAD_REQUEST
        assert resp2.json()["code"] == "INVALID_PARAMETERS"
