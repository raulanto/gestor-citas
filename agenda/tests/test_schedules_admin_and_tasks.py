"""Tests for schedule admin integration, Celery maintenance tasks, and management commands."""

import datetime
from io import StringIO
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.db import transaction

from agenda.admin import ScheduleExceptionAdmin, WorkerAdmin, WorkScheduleAdmin
from agenda.constants import AppointmentStatus
from agenda.models import ExceptionKind, ScheduleException, Weekday, Worker, WorkSchedule
from agenda.services.schedules import revalidate_all
from agenda.tasks import waitlist_maintenance_task
from agenda.tests.factories import (
    AppointmentFactory,
    DayConfigFactory,
    ScheduleExceptionFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def tz():
    return ZoneInfo(settings.TIME_ZONE)


class DummyAdminSite(AdminSite):
    pass


@pytest.mark.django_db
def test_admin_worker_deactivation_revalidates_and_warns(tz, monkeypatch):
    target_date = datetime.date(2026, 10, 15)  # Thursday, weekday 3
    worker = WorkerFactory(is_active=True)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    site = DummyAdminSite()
    worker_admin = WorkerAdmin(Worker, site)

    mock_request = MagicMock()
    mock_request.user = None
    mock_messages = []
    monkeypatch.setattr(messages, "warning", lambda req, msg: mock_messages.append(msg))

    worker.is_active = False
    with transaction.atomic():
        worker_admin.save_model(mock_request, obj=worker, form=MagicMock(), change=True)

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
    assert len(mock_messages) == 1
    assert "enviadas a espera: 1" in mock_messages[0]


@pytest.mark.django_db
def test_admin_work_schedule_change_revalidates_and_warns(tz, monkeypatch):
    target_date = datetime.date(2026, 10, 15)
    worker = WorkerFactory()
    ws = WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    site = DummyAdminSite()
    ws_admin = WorkScheduleAdmin(WorkSchedule, site)

    mock_request = MagicMock()
    mock_request.user = None
    mock_messages = []
    monkeypatch.setattr(messages, "warning", lambda req, msg: mock_messages.append(msg))

    ws.end_time = datetime.time(12, 0)
    with transaction.atomic():
        ws_admin.save_model(mock_request, obj=ws, form=MagicMock(), change=True)

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
    assert len(mock_messages) == 1
    assert "enviadas a espera: 1" in mock_messages[0]


@pytest.mark.django_db
def test_admin_schedule_exception_addition_revalidates_and_warns(tz, monkeypatch):
    target_date = datetime.date(2026, 10, 15)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    site = DummyAdminSite()
    exc_admin = ScheduleExceptionAdmin(ScheduleException, site)

    mock_request = MagicMock()
    mock_request.user = None
    mock_messages = []
    monkeypatch.setattr(messages, "warning", lambda req, msg: mock_messages.append(msg))

    exc = ScheduleExceptionFactory.build(
        worker=worker,
        date=target_date,
        kind=ExceptionKind.ABSENCE,
        reason="Enfermedad",
    )
    with transaction.atomic():
        exc_admin.save_model(mock_request, obj=exc, form=MagicMock(), change=False)

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
    assert len(mock_messages) == 1
    assert "enviadas a espera: 1" in mock_messages[0]


@pytest.mark.django_db
def test_revalidate_all_sweeps_direct_orm_inconsistencies(tz):
    target_date = datetime.date(2026, 10, 15)
    worker = WorkerFactory()
    schedule = WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # Bypass services and hooks by direct ORM update
    WorkSchedule.objects.filter(id=schedule.id).update(end_time=datetime.time(12, 0))

    # At this point, appt is still CONFIRMED with worker, which is invalid
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED

    # revalidate_all sweeps and fixes it
    now = datetime.datetime.combine(target_date, datetime.time(8, 0), tzinfo=tz)
    results = revalidate_all(now=now, from_date=target_date)

    assert len(results) >= 1
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED
    assert appt.worker is None


@pytest.mark.django_db
def test_waitlist_maintenance_task_executes_sweep(tz):
    target_date = datetime.date(2026, 10, 15)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    res = waitlist_maintenance_task.delay()
    assert res.successful()

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED


@pytest.mark.django_db
def test_management_command_revalidate_assignments(tz):
    worker = WorkerFactory()
    target_date = datetime.date(2026, 10, 15)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),
    )
    service = ServiceFactory(duration_minutes=30)
    appt = AppointmentFactory(
        service=service,
        worker=worker,
        date=target_date,
        start_at=datetime.datetime.combine(target_date, datetime.time(15, 0), tzinfo=tz),
        status=AppointmentStatus.CONFIRMED,
    )

    # 1. Run for all workers
    out = StringIO()
    call_command("revalidate_assignments", stdout=out)
    output = out.getvalue()
    assert "Revalidación completada" in output

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.WAITLISTED

    # 2. Run for specific worker
    out2 = StringIO()
    call_command("revalidate_assignments", worker=worker.id, stdout=out2)
    output2 = out2.getvalue()
    assert f"Revalidando citas para el trabajador {worker.id}..." in output2
