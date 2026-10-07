"""Tests for GET /api/v1/availability/ endpoint."""

import datetime

import pytest
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

from agenda.models import DayConfig, Weekday, WorkSchedule
from agenda.tests.factories import ServiceFactory, WorkerFactory


@pytest.mark.django_db
class TestAvailabilityAPI:
    @freeze_time("2026-10-12 08:00:00-06:00")
    def test_get_availability_success(self):
        client = APIClient()
        service = ServiceFactory(name="Consulta General", duration_minutes=30)
        target_date = "2026-10-14"  # Wednesday

        DayConfig.objects.create(
            weekday=Weekday.WEDNESDAY,
            is_open=True,
            max_appointments=20,
        )

        w1 = WorkerFactory(full_name="Dra. Ana", is_active=True)
        WorkSchedule.objects.create(
            worker=w1,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(11, 0),
        )

        w2 = WorkerFactory(full_name="Dr. Carlos", is_active=True)
        WorkSchedule.objects.create(
            worker=w2,
            weekday=Weekday.WEDNESDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(11, 0),
        )

        response = client.get(f"/api/v1/availability/?date={target_date}&service={service.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["date"] == target_date
        assert data["service"] == {
            "id": service.id,
            "name": "Consulta General",
            "duration_minutes": 30,
        }
        assert data["is_open"] is True
        assert data["reason"] is None
        assert data["effective_quota"] == 8  # 4 slots * 2 workers
        assert data["remaining_quota"] == 8
        assert isinstance(data["slots"], list)
        assert len(data["slots"]) > 0

        # Validate slot format and timezone offset
        first_slot = data["slots"][0]
        assert first_slot["start"] == "2026-10-14T09:00:00-06:00"
        assert first_slot["end"] == "2026-10-14T09:30:00-06:00"
        assert first_slot["free_workers"] == 2

    def test_missing_date_parameter_returns_400(self):
        client = APIClient()
        service = ServiceFactory()
        response = client.get(f"/api/v1/availability/?service={service.id}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["code"] == "INVALID_PARAMETERS"
        assert "date" in data["errors"]

    def test_invalid_date_format_returns_400(self):
        client = APIClient()
        service = ServiceFactory()
        response = client.get(f"/api/v1/availability/?date=14-10-2026&service={service.id}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["code"] == "INVALID_PARAMETERS"
        assert "date" in data["errors"]

    def test_missing_service_parameter_returns_400(self):
        client = APIClient()
        response = client.get("/api/v1/availability/?date=2026-10-14")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["code"] == "INVALID_PARAMETERS"
        assert "service" in data["errors"]

    def test_nonexistent_service_returns_404(self):
        client = APIClient()
        response = client.get("/api/v1/availability/?date=2026-10-14&service=99999")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["code"] == "service_not_found"

    def test_inactive_service_returns_404(self):
        client = APIClient()
        service = ServiceFactory(is_active=False)
        response = client.get(f"/api/v1/availability/?date=2026-10-14&service={service.id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["code"] == "service_not_found"
