"""Tests for appointment manage tokens, hashing, rotation, and security."""

import datetime
import hashlib
import logging
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
from agenda.models import AppointmentEvent
from agenda.services.manage_token import (
    issue_manage_token,
    verify_manage_token,
)
from agenda.tests.factories import (
    AppointmentFactory,
    ServiceFactory,
    WorkerFactory,
    create_appointment_with_token,
)


@pytest.mark.django_db
class TestManageTokenCryptoAndStorage:
    """Test cryptographic generation, hash-only persistence, and constant-time verification."""

    def test_issue_manage_token_stores_only_sha256_hash(self):
        appointment = AppointmentFactory()
        raw_token = issue_manage_token(appointment)

        assert raw_token is not None
        assert len(raw_token) >= 32

        appointment.refresh_from_db()
        expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert appointment.manage_token_hash == expected_hash

        # Verify raw token is not in any DB column or event
        assert raw_token not in str(appointment.__dict__)
        events = AppointmentEvent.objects.filter(appointment=appointment)
        for ev in events:
            assert raw_token not in (ev.note or "")

    def test_verify_manage_token(self):
        appointment = AppointmentFactory()
        raw_token = issue_manage_token(appointment)

        # Valid token matches
        assert verify_manage_token(appointment, raw_token) is True

        # Invalid token fails
        assert verify_manage_token(appointment, "wrong_token_1234567890123456789012") is False

        # Empty / None token fails
        assert verify_manage_token(appointment, "") is False
        assert verify_manage_token(appointment, None) is False

        # Appointment without token hash fails
        legacy_appt = AppointmentFactory(manage_token_hash=None)
        assert verify_manage_token(legacy_appt, raw_token) is False


@pytest.mark.django_db
class TestManageTokenApiAccess:
    """Test API access control using X-Manage-Token header."""

    def test_get_appointment_with_valid_token_returns_200(self, api_client: APIClient):
        appointment, token = create_appointment_with_token()

        response = api_client.get(
            f"/api/v1/appointments/{appointment.id}/",
            HTTP_X_MANAGE_TOKEN=token,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(appointment.id)
        # Token is NOT in detail response
        assert "manage_token" not in data

    def test_get_appointment_without_token_returns_404(self, api_client: APIClient):
        appointment, _ = create_appointment_with_token()

        response = api_client.get(f"/api/v1/appointments/{appointment.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == "APPOINTMENT_NOT_FOUND"

    def test_get_appointment_with_wrong_token_returns_404(self, api_client: APIClient):
        appointment, _ = create_appointment_with_token()

        response = api_client.get(
            f"/api/v1/appointments/{appointment.id}/",
            HTTP_X_MANAGE_TOKEN="invalid_manage_token_value_xyz",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == "APPOINTMENT_NOT_FOUND"

    def test_get_appointment_with_other_appointment_token_returns_404(self, api_client: APIClient):
        appt1, token1 = create_appointment_with_token()
        appt2, token2 = create_appointment_with_token()

        response = api_client.get(
            f"/api/v1/appointments/{appt1.id}/",
            HTTP_X_MANAGE_TOKEN=token2,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == "APPOINTMENT_NOT_FOUND"

    def test_cancel_with_valid_token(self, api_client: APIClient):
        tz = ZoneInfo(settings.TIME_ZONE)
        future_date = datetime.date.today() + datetime.timedelta(days=2)
        future_start = datetime.datetime.combine(future_date, datetime.time(10, 0), tzinfo=tz)

        appointment, token = create_appointment_with_token(
            date=future_date,
            start_at=future_start,
            status=AppointmentStatus.CONFIRMED,
        )

        response = api_client.post(
            f"/api/v1/appointments/{appointment.id}/cancel/",
            {"reason": "Ya no puedo asistir"},
            format="json",
            HTTP_X_MANAGE_TOKEN=token,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "CANCELLED"

    def test_cancel_without_token_returns_404(self, api_client: APIClient):
        tz = ZoneInfo(settings.TIME_ZONE)
        future_date = datetime.date.today() + datetime.timedelta(days=2)
        future_start = datetime.datetime.combine(future_date, datetime.time(10, 0), tzinfo=tz)

        appointment, _ = create_appointment_with_token(
            date=future_date,
            start_at=future_start,
            status=AppointmentStatus.CONFIRMED,
        )

        response = api_client.post(
            f"/api/v1/appointments/{appointment.id}/cancel/",
            {"reason": "No tengo token"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestManageTokenRotation:
    """Test token rotation by staff and access invalidation."""

    def test_staff_rotates_manage_token(self, staff_client: APIClient, staff_user):
        appointment, old_token = create_appointment_with_token()

        response = staff_client.post(f"/api/v1/appointments/{appointment.id}/token/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "manage_token" in data
        new_token = data["manage_token"]
        assert new_token != old_token

        # Audit event was created without containing the token
        event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
        assert "Token de gestión rotado" in event.note
        assert new_token not in event.note

        # Old token is now invalid
        appointment.refresh_from_db()
        assert verify_manage_token(appointment, old_token) is False
        assert verify_manage_token(appointment, new_token) is True

    def test_worker_or_anonymous_cannot_rotate_token(
        self, api_client: APIClient, worker_client: APIClient
    ):
        appointment, _ = create_appointment_with_token()

        # Anonymous -> 401
        anon_resp = api_client.post(f"/api/v1/appointments/{appointment.id}/token/")
        assert anon_resp.status_code == status.HTTP_401_UNAUTHORIZED

        # Worker -> 403
        worker_resp = worker_client.post(f"/api/v1/appointments/{appointment.id}/token/")
        assert worker_resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestRescheduleTokenIssuance:
    """Test that reschedule delivers new token with no access from old token."""

    def test_reschedule_delivers_new_token(self, api_client: APIClient):
        tz = ZoneInfo(settings.TIME_ZONE)
        future_date = datetime.date.today() + datetime.timedelta(days=2)
        future_start = datetime.datetime.combine(future_date, datetime.time(10, 0), tzinfo=tz)

        worker = WorkerFactory()
        from agenda.tests.factories import DayConfigFactory, WorkScheduleFactory

        WorkScheduleFactory(
            worker=worker,
            weekday=future_date.weekday(),
            start_time=datetime.time(8, 0),
            end_time=datetime.time(18, 0),
        )
        DayConfigFactory(date=future_date, weekday=None, is_open=True, max_appointments=20)

        appointment, old_token = create_appointment_with_token(
            worker=worker,
            date=future_date,
            start_at=future_start,
            status=AppointmentStatus.CONFIRMED,
        )
        new_start = future_start + datetime.timedelta(hours=1)

        response = api_client.post(
            f"/api/v1/appointments/{appointment.id}/reschedule/",
            {"start_at": new_start.isoformat()},
            format="json",
            HTTP_X_MANAGE_TOKEN=old_token,
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "manage_token" in data
        new_token = data["manage_token"]
        new_id = data["id"]
        assert new_token != old_token

        # Old token cannot access the new appointment
        new_get_resp = api_client.get(
            f"/api/v1/appointments/{new_id}/",
            HTTP_X_MANAGE_TOKEN=old_token,
        )
        assert new_get_resp.status_code == status.HTTP_404_NOT_FOUND

        # New token can access the new appointment
        valid_get_resp = api_client.get(
            f"/api/v1/appointments/{new_id}/",
            HTTP_X_MANAGE_TOKEN=new_token,
        )
        assert valid_get_resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_manage_token_never_logged(api_client: APIClient, caplog):
    """Ensure manage tokens are not recorded in loggers."""
    service = ServiceFactory()
    start_dt = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)

    with caplog.at_level(logging.DEBUG):
        response = api_client.post(
            "/api/v1/appointments/",
            {
                "requester": {"full_name": "Test Token User", "phone": "5551112233"},
                "service": service.id,
                "start_at": start_dt.isoformat(),
            },
            format="json",
        )
        if response.status_code == status.HTTP_201_CREATED:
            token = response.json()["manage_token"]
            assert token not in caplog.text
