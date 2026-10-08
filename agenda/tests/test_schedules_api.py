"""Tests for Phase 6 schedule and day configuration REST API endpoints."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agenda.constants import AppointmentStatus
from agenda.models import Appointment, DayConfig, ExceptionKind, Weekday, WorkSchedule
from agenda.tests.factories import (
    AppointmentFactory,
    DayConfigFactory,
    ScheduleExceptionFactory,
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
    return User.objects.create_user(
        username="staff_user",
        email="staff@example.com",
        password="password123",
        is_staff=True,
    )


@pytest.fixture
def worker_user():
    return User.objects.create_user(
        username="worker_user",
        email="worker@example.com",
        password="password123",
    )


@pytest.fixture
def other_worker_user():
    return User.objects.create_user(
        username="other_worker",
        email="other@example.com",
        password="password123",
    )


@pytest.mark.django_db
def test_permissions_matrix(api_client, staff_user, worker_user, other_worker_user):
    worker = WorkerFactory(user=worker_user)
    other_worker = WorkerFactory(user=other_worker_user)
    target_date = datetime.date(2026, 10, 15)

    # 1. Anonymous -> 401 / 403
    resp = api_client.get(f"/api/v1/workers/{worker.id}/schedule/")
    assert resp.status_code in (401, 403)

    resp = api_client.get(f"/api/v1/day-configs/{target_date.isoformat()}/")
    assert resp.status_code in (401, 403)

    # 2. Worker user editing another worker -> 403
    api_client.force_authenticate(user=worker_user)
    resp = api_client.put(
        f"/api/v1/workers/{other_worker.id}/schedule/",
        {"entries": []},
        format="json",
    )
    assert resp.status_code == 403

    resp = api_client.patch(
        f"/api/v1/workers/{worker.id}/",
        {"is_active": False},
        format="json",
    )
    assert resp.status_code == 403  # Worker cannot deactivate themselves

    resp = api_client.get(f"/api/v1/day-configs/{target_date.isoformat()}/")
    assert resp.status_code == 403

    # 3. Staff user can access everything
    api_client.force_authenticate(user=staff_user)
    resp = api_client.get(f"/api/v1/workers/{worker.id}/schedule/")
    assert resp.status_code == 200

    resp = api_client.get(f"/api/v1/day-configs/{target_date.isoformat()}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_get_and_put_worker_schedule(api_client, worker_user, tz):
    worker = WorkerFactory(user=worker_user)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    api_client.force_authenticate(user=worker_user)

    # GET schedule
    resp = api_client.get(f"/api/v1/workers/{worker.id}/schedule/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["weekly_schedule"]) == 1
    assert data["weekly_schedule"][0]["weekday"] == 3

    # PUT invalid entries (end_time <= start_time) -> 400
    bad_payload = {
        "entries": [
            {
                "weekday": 3,
                "start_time": "17:00",
                "end_time": "09:00",
            }
        ]
    }
    resp = api_client.put(f"/api/v1/workers/{worker.id}/schedule/", bad_payload, format="json")
    assert resp.status_code == 400

    # PUT shortening shift without confirm -> 409 with impact
    short_payload = {
        "entries": [
            {
                "weekday": 3,
                "start_time": "09:00",
                "end_time": "12:00",
            }
        ],
        "confirm": False,
        "dry_run": False,
    }
    resp = api_client.put(f"/api/v1/workers/{worker.id}/schedule/", short_payload, format="json")
    assert resp.status_code == 409
    err_data = resp.json()
    assert err_data["code"] == "SCHEDULE_CHANGE_REQUIRES_CONFIRMATION"
    assert err_data["impact"]["waitlisted"] == 1

    # PUT with dry_run=True -> 200 with applied=false and impact
    dry_payload = {**short_payload, "dry_run": True}
    resp = api_client.put(f"/api/v1/workers/{worker.id}/schedule/", dry_payload, format="json")
    assert resp.status_code == 200
    dry_data = resp.json()
    assert dry_data["applied"] is False
    assert dry_data["impact"]["waitlisted"] == 1

    # PUT with confirm=True -> 200 with applied=true
    conf_payload = {**short_payload, "confirm": True}
    resp = api_client.put(f"/api/v1/workers/{worker.id}/schedule/", conf_payload, format="json")
    assert resp.status_code == 200
    conf_data = resp.json()
    assert conf_data["applied"] is True

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED


@pytest.mark.django_db
def test_worker_exceptions_api(api_client, worker_user, tz):
    worker = WorkerFactory(user=worker_user)
    target_date = datetime.date(2026, 10, 15)
    api_client.force_authenticate(user=worker_user)

    # POST exception
    exc_payload = {
        "date": target_date.isoformat(),
        "kind": "ABSENCE",
        "reason": "Permiso especial",
        "confirm": True,
    }
    resp = api_client.post(f"/api/v1/workers/{worker.id}/exceptions/", exc_payload, format="json")
    assert resp.status_code == 201
    exc_id = resp.json()["exception"]["id"]

    # DELETE exception
    resp = api_client.delete(f"/api/v1/workers/{worker.id}/exceptions/{exc_id}/")
    assert resp.status_code == 200
    assert resp.json()["applied"] is True


@pytest.mark.django_db
def test_staff_patch_worker_is_active(api_client, staff_user, tz):
    worker = WorkerFactory(is_active=True)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    target_date = datetime.date(2026, 10, 15)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    api_client.force_authenticate(user=staff_user)

    # PATCH without confirm -> 409
    resp = api_client.patch(
        f"/api/v1/workers/{worker.id}/",
        {"is_active": False, "confirm": False},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["impact"]["waitlisted"] == 1

    # PATCH with confirm -> 200
    resp = api_client.patch(
        f"/api/v1/workers/{worker.id}/",
        {"is_active": False, "confirm": True},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] is True

    worker.refresh_from_db()
    assert worker.is_active is False
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED


@pytest.mark.django_db
def test_day_configs_api(api_client, staff_user, tz):
    target_date = datetime.date(2026, 10, 15)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    api_client.force_authenticate(user=staff_user)

    # 1. GET date config
    resp = api_client.get(f"/api/v1/day-configs/{target_date.isoformat()}/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == target_date.isoformat()
    assert data["summary"]["active_count"] == 1

    # 2. PUT date config (closing day with active appointments -> returns warning, doesn't cancel)
    put_payload = {
        "is_open": False,
        "max_appointments": 5,
        "note": "Mantenimiento",
    }
    resp = api_client.put(
        f"/api/v1/day-configs/{target_date.isoformat()}/",
        put_payload,
        format="json",
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["warnings"]["active_appointments_on_closed_day"] == 1
    assert res_data["config"]["is_open"] is False

    # 3. GET / PUT weekday config
    resp = api_client.get("/api/v1/day-configs/weekday/3/")
    assert resp.status_code == 200

    resp = api_client.put(
        "/api/v1/day-configs/weekday/3/",
        {"max_appointments": 10, "is_open": True},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["max_appointments"] == 10


@pytest.mark.django_db
def test_appointments_unserviceable_filter(api_client, staff_user, tz):
    target_date = datetime.date(2026, 10, 15)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),
    )
    service = ServiceFactory(duration_minutes=30)

    # 1. Serviceable waitlisted appointment (10:00)
    appt_serv = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # 2. Unserviceable waitlisted appointment (15:00)
    appt_unserv = AppointmentFactory(
        service=service,
        worker=None,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    api_client.force_authenticate(user=staff_user)

    resp = api_client.get("/api/v1/appointments/?unserviceable=true")
    assert resp.status_code == 200
    data = resp.json()
    ids = [item["id"] for item in data]
    assert appt_unserv.id in ids
    assert appt_serv.id not in ids
