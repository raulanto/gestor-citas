"""Tests for role matrix verification across all endpoints and user roles."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
from agenda.tests.factories import (
    ServiceFactory,
    WorkerUserFactory,
    create_appointment_with_token,
)


@pytest.mark.django_db
class TestRolesMatrix:
    """Comprehensive test matrix covering all user roles against all endpoints."""

    def test_health_check_public(
        self,
        api_client: APIClient,
        staff_client: APIClient,
        worker_client: APIClient,
    ):
        for client in [api_client, staff_client, worker_client]:
            resp = client.get("/api/v1/health/")
            assert resp.status_code == status.HTTP_200_OK

    def test_availability_public(self, api_client: APIClient):
        service = ServiceFactory()
        resp = api_client.get(f"/api/v1/availability/?date=2026-10-20&service={service.id}")
        assert resp.status_code == status.HTTP_200_OK

    def test_appointments_list_staff_only(
        self,
        api_client: APIClient,
        worker_client: APIClient,
        staff_client: APIClient,
        auth_client_for_user,
        plain_user,
    ):
        # Anonymous -> 401
        assert api_client.get("/api/v1/appointments/").status_code == status.HTTP_401_UNAUTHORIZED
        # Worker -> 403
        assert worker_client.get("/api/v1/appointments/").status_code == status.HTTP_403_FORBIDDEN
        # Plain user -> 403
        plain_client = auth_client_for_user(plain_user)
        assert plain_client.get("/api/v1/appointments/").status_code == status.HTTP_403_FORBIDDEN
        # Staff -> 200
        assert staff_client.get("/api/v1/appointments/").status_code == status.HTTP_200_OK

    def test_waitlist_staff_only(
        self,
        api_client: APIClient,
        worker_client: APIClient,
        staff_client: APIClient,
        auth_client_for_user,
        plain_user,
    ):
        url = "/api/v1/waitlist/?date=2026-10-20"
        assert api_client.get(url).status_code == status.HTTP_401_UNAUTHORIZED
        assert worker_client.get(url).status_code == status.HTTP_403_FORBIDDEN
        plain_client = auth_client_for_user(plain_user)
        assert plain_client.get(url).status_code == status.HTTP_403_FORBIDDEN
        assert staff_client.get(url).status_code == status.HTTP_200_OK

    def test_appointment_complete_and_no_show_permissions(
        self,
        api_client: APIClient,
        auth_client_for_user,
        staff_client: APIClient,
        plain_user,
    ):
        worker1_user = WorkerUserFactory()
        worker2_user = WorkerUserFactory()
        client1 = auth_client_for_user(worker1_user)
        client2 = auth_client_for_user(worker2_user)
        plain_client = auth_client_for_user(plain_user)

        appt, _ = create_appointment_with_token(
            worker=worker1_user.worker_profile,
            status=AppointmentStatus.CONFIRMED,
        )

        # Anonymous -> 401
        res = api_client.post(f"/api/v1/appointments/{appt.id}/complete/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        # Plain user -> 403
        res = plain_client.post(f"/api/v1/appointments/{appt.id}/complete/")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        # Other worker -> 403
        res = client2.post(f"/api/v1/appointments/{appt.id}/complete/")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        # Assigned worker -> 200
        res = client1.post(f"/api/v1/appointments/{appt.id}/complete/")
        assert res.status_code == status.HTTP_200_OK

        # Test no-show on another appointment
        appt_ns, _ = create_appointment_with_token(
            worker=worker1_user.worker_profile,
            status=AppointmentStatus.CONFIRMED,
        )
        # Staff -> 200
        res = staff_client.post(f"/api/v1/appointments/{appt_ns.id}/no-show/")
        assert res.status_code == status.HTTP_200_OK

    def test_cancel_force_permission(
        self,
        api_client: APIClient,
        auth_client_for_user,
        staff_client: APIClient,
    ):
        worker_user = WorkerUserFactory()
        worker_client = auth_client_for_user(worker_user)

        tz = ZoneInfo(settings.TIME_ZONE)
        future_date = datetime.date.today() + datetime.timedelta(days=2)
        future_start = datetime.datetime.combine(future_date, datetime.time(10, 0), tzinfo=tz)

        appt, token = create_appointment_with_token(
            worker=worker_user.worker_profile,
            date=future_date,
            start_at=future_start,
            status=AppointmentStatus.CONFIRMED,
        )

        # Requester with manage token sending force=True -> 403
        resp = api_client.post(
            f"/api/v1/appointments/{appt.id}/cancel/",
            {"reason": "test", "force": True},
            format="json",
            HTTP_X_MANAGE_TOKEN=token,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        # Worker sending force=True -> 403
        resp2 = worker_client.post(
            f"/api/v1/appointments/{appt.id}/cancel/",
            {"reason": "test", "force": True},
            format="json",
        )
        assert resp2.status_code == status.HTTP_403_FORBIDDEN

        # Staff sending force=True -> 200
        resp3 = staff_client.post(
            f"/api/v1/appointments/{appt.id}/cancel/",
            {"reason": "staff forced", "force": True},
            format="json",
        )
        assert resp3.status_code == status.HTTP_200_OK

    def test_worker_schedule_and_exceptions_permissions(
        self,
        api_client: APIClient,
        auth_client_for_user,
        staff_client: APIClient,
    ):
        worker1_user = WorkerUserFactory()
        worker2_user = WorkerUserFactory()
        client1 = auth_client_for_user(worker1_user)
        client2 = auth_client_for_user(worker2_user)
        w1_id = worker1_user.worker_profile.id

        # Anonymous -> 401
        res = api_client.get(f"/api/v1/workers/{w1_id}/schedule/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        # Worker 2 attempting on Worker 1 -> 403
        res = client2.get(f"/api/v1/workers/{w1_id}/schedule/")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        # Worker 1 on Worker 1 -> 200
        res = client1.get(f"/api/v1/workers/{w1_id}/schedule/")
        assert res.status_code == status.HTTP_200_OK
        # Staff on Worker 1 -> 200
        res = staff_client.get(f"/api/v1/workers/{w1_id}/schedule/")
        assert res.status_code == status.HTTP_200_OK

    def test_worker_patch_active_status_staff_only(
        self,
        api_client: APIClient,
        auth_client_for_user,
        staff_client: APIClient,
    ):
        worker1_user = WorkerUserFactory()
        client1 = auth_client_for_user(worker1_user)
        w1_id = worker1_user.worker_profile.id

        # Anonymous -> 401
        res = api_client.patch(f"/api/v1/workers/{w1_id}/", {"is_active": False}, format="json")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        # Worker himself -> 403
        res = client1.patch(f"/api/v1/workers/{w1_id}/", {"is_active": False}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        # Staff -> 200
        res = staff_client.patch(
            f"/api/v1/workers/{w1_id}/",
            {"is_active": False, "confirm": True},
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK

    def test_day_configs_staff_only(
        self,
        api_client: APIClient,
        worker_client: APIClient,
        staff_client: APIClient,
    ):
        date_url = "/api/v1/day-configs/2026-10-20/"
        assert api_client.get(date_url).status_code == status.HTTP_401_UNAUTHORIZED
        assert worker_client.get(date_url).status_code == status.HTTP_403_FORBIDDEN
        assert staff_client.get(date_url).status_code == status.HTTP_200_OK
