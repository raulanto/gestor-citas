"""Tests for admin triggers, celery tasks, beat schedule, and management commands."""

import datetime
from io import StringIO
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.db import transaction

from agenda.admin import DayConfigAdmin, WorkerAdmin
from agenda.constants import AppointmentStatus
from agenda.models import DayConfig, Weekday, Worker
from agenda.services.waitlist import schedule_waitlist_processing
from agenda.tasks import (
    process_waitlist_all_task,
    process_waitlist_task,
    waitlist_maintenance_task,
)
from agenda.tests.factories import (
    AppointmentFactory,
    DayConfigFactory,
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
def test_admin_work_schedule_trigger(django_capture_on_commit_callbacks, tz):
    """Admin save_formset on WorkerAdmin triggers waitlist processing on commit."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    site = DummyAdminSite()
    worker_admin = WorkerAdmin(Worker, site)
    worker = WorkerFactory()

    request = MagicMock()

    # Formset saving a WorkSchedule inline
    formset = MagicMock()
    WorkScheduleFactory(
        worker=worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            worker_admin.save_formset(request, form=MagicMock(), formset=formset, change=True)

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == worker


@pytest.mark.django_db
def test_admin_day_config_reopen_trigger(django_capture_on_commit_callbacks, tz):
    """Admin save_model on DayConfigAdmin reopening a day triggers waitlist processing on commit."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )

    day_cfg = DayConfigFactory(
        weekday=None,
        date=target_date,
        is_open=False,
        max_appointments=20,
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    site = DummyAdminSite()
    day_admin = DayConfigAdmin(DayConfig, site)
    request = MagicMock()

    day_cfg.is_open = True
    day_cfg.save()

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            day_admin.save_model(request, obj=day_cfg, form=MagicMock(), change=True)

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.worker == worker


@pytest.mark.django_db
def test_multiple_triggers_in_same_transaction_enqueued_once(django_capture_on_commit_callbacks):
    """Multiple schedule_waitlist_processing calls in the same transaction execute callback once."""
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with transaction.atomic():
            schedule_waitlist_processing()
            schedule_waitlist_processing()
            schedule_waitlist_processing()

    # Only 1 on_commit callback should have been registered
    assert len(callbacks) == 1


@pytest.mark.django_db
def test_celery_eager_tasks(tz):
    """Celery tasks execute synchronously and promote appointments in eager mode."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    # 1. process_waitlist_task
    res = process_waitlist_task.delay(target_date.isoformat())
    assert res.successful()

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED

    # 2. process_waitlist_all_task
    res_all = process_waitlist_all_task.delay()
    assert res_all.successful()

    # 3. waitlist_maintenance_task
    res_maint = waitlist_maintenance_task.delay()
    assert res_maint.successful()


def test_celery_beat_schedule_configuration():
    """Verify Celery Beat schedule contains waitlist sweep task and configured interval."""
    beat_schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
    assert "waitlist-maintenance-sweep" in beat_schedule
    sweep_config = beat_schedule["waitlist-maintenance-sweep"]
    assert sweep_config["task"] == "agenda.tasks.waitlist_maintenance_task"
    assert sweep_config["schedule"] == settings.WAITLIST_SWEEP_MINUTES * 60


@pytest.mark.django_db
def test_management_command_process_waitlist_with_date(tz):
    """Management command process_waitlist --date YYYY-MM-DD outputs assigned count."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    out = StringIO()
    call_command("process_waitlist", date="2026-10-12", stdout=out)
    output = out.getvalue()
    assert "1 citas asignadas" in output

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED


@pytest.mark.django_db
def test_management_command_process_waitlist_all_dates(tz):
    """Management command process_waitlist without date processes all dates."""
    target_date = datetime.date(2026, 10, 12)
    service = ServiceFactory(duration_minutes=30)
    worker = WorkerFactory()
    WorkScheduleFactory(
        worker=worker,
        weekday=Weekday.MONDAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=20,
    )

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=target_date,
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 12, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    out = StringIO()
    call_command("process_waitlist", stdout=out)
    output = out.getvalue()
    assert "1 citas asignadas en total" in output

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CONFIRMED


@pytest.mark.django_db
def test_management_command_expire_waitlist(tz):
    """Management command expire_waitlist marks past waitlisted appointments as EXPIRED."""
    service = ServiceFactory(duration_minutes=30)
    past_date = datetime.date(2026, 10, 1)

    appt = AppointmentFactory(
        worker=None,
        service=service,
        date=past_date,
        start_at=datetime.datetime(2026, 10, 1, 10, 0, tzinfo=tz),
        end_at=datetime.datetime(2026, 10, 1, 10, 30, tzinfo=tz),
        status=AppointmentStatus.WAITLISTED,
    )

    out = StringIO()
    call_command("expire_waitlist", stdout=out)
    output = out.getvalue()
    assert "expiradas 1 citas en espera" in output

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.EXPIRED
