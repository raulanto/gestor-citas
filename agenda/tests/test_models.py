import datetime

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory

from agenda.admin import DayConfigAdmin, RequesterAdmin, ServiceAdmin, WorkerAdmin
from agenda.models import (
    DayConfig,
    ExceptionKind,
    Requester,
    ScheduleException,
    Service,
    Weekday,
    Worker,
    WorkSchedule,
)
from agenda.tests.factories import (
    DayConfigFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.mark.django_db
class TestServiceModel:
    def test_valid_durations_accepted(self):
        for duration in (5, 30, 60):
            service = ServiceFactory.build(name=f"Servicio {duration}", duration_minutes=duration)
            service.full_clean()
            service.save()
            assert service.pk is not None

    @pytest.mark.parametrize("invalid_duration", [4, 61, 0, 100])
    def test_invalid_durations_rejected_in_clean(self, invalid_duration):
        service = ServiceFactory.build(duration_minutes=invalid_duration)
        with pytest.raises(ValidationError) as exc_info:
            service.full_clean()
        assert "duration_minutes" in exc_info.value.message_dict

    @pytest.mark.parametrize("invalid_duration", [4, 61])
    def test_invalid_durations_rejected_in_database_constraint(self, invalid_duration):
        with pytest.raises(IntegrityError):
            Service.objects.create(
                name=f"Direct DB {invalid_duration}",
                duration_minutes=invalid_duration,
            )

    def test_unique_name_constraint(self):
        ServiceFactory(name="Consulta Única")
        with pytest.raises(IntegrityError):
            Service.objects.create(name="Consulta Única", duration_minutes=30)


@pytest.mark.django_db
class TestRequesterModel:
    def test_valid_with_phone_or_email(self):
        r1 = RequesterFactory.build(phone="5551234567", email="")
        r1.full_clean()
        r1.save()

        r2 = RequesterFactory.build(phone="", email="test@example.com")
        r2.full_clean()
        r2.save()

        r3 = RequesterFactory.build(phone="5551234567", email="test@example.com")
        r3.full_clean()
        r3.save()

    def test_rejected_when_both_phone_and_email_empty_in_clean(self):
        requester = RequesterFactory.build(phone="", email="")
        with pytest.raises(ValidationError):
            requester.full_clean()

    def test_rejected_when_both_empty_in_database_constraint(self):
        with pytest.raises(IntegrityError):
            Requester.objects.create(full_name="Sin contacto", phone="", email="")


@pytest.mark.django_db
class TestWorkScheduleModel:
    def test_valid_schedule_with_and_without_break(self):
        worker = WorkerFactory()

        # With valid break
        s1 = WorkScheduleFactory.build(
            worker=worker,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            break_start=datetime.time(13, 0),
            break_end=datetime.time(14, 0),
        )
        s1.full_clean()
        s1.save()

        # Without break
        s2 = WorkScheduleFactory.build(
            worker=worker,
            weekday=Weekday.TUESDAY,
            start_time=datetime.time(8, 0),
            end_time=datetime.time(16, 0),
            break_start=None,
            break_end=None,
        )
        s2.full_clean()
        s2.save()

    def test_end_time_before_or_equal_start_time_rejected(self):
        worker = WorkerFactory()
        sched = WorkScheduleFactory.build(
            worker=worker,
            start_time=datetime.time(17, 0),
            end_time=datetime.time(9, 0),
            break_start=None,
            break_end=None,
        )
        with pytest.raises(ValidationError):
            sched.full_clean()

        with pytest.raises(IntegrityError):
            WorkSchedule.objects.create(
                worker=worker,
                weekday=Weekday.WEDNESDAY,
                start_time=datetime.time(17, 0),
                end_time=datetime.time(9, 0),
            )

    def test_incomplete_break_rejected(self):
        worker = WorkerFactory()
        sched = WorkScheduleFactory.build(
            worker=worker,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            break_start=datetime.time(13, 0),
            break_end=None,
        )
        with pytest.raises(ValidationError):
            sched.full_clean()

        with pytest.raises(IntegrityError):
            WorkSchedule.objects.create(
                worker=worker,
                weekday=Weekday.THURSDAY,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0),
                break_start=datetime.time(13, 0),
                break_end=None,
            )

    @pytest.mark.parametrize(
        "b_start,b_end",
        [
            (datetime.time(8, 0), datetime.time(12, 0)),  # break before shift start
            (datetime.time(12, 0), datetime.time(18, 0)),  # break after shift end
            (datetime.time(14, 0), datetime.time(13, 0)),  # break end before break start
        ],
    )
    def test_break_outside_shift_rejected(self, b_start, b_end):
        worker = WorkerFactory()
        sched = WorkScheduleFactory.build(
            worker=worker,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            break_start=b_start,
            break_end=b_end,
        )
        with pytest.raises(ValidationError):
            sched.full_clean()

        with pytest.raises(IntegrityError):
            WorkSchedule.objects.create(
                worker=worker,
                weekday=Weekday.FRIDAY,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0),
                break_start=b_start,
                break_end=b_end,
            )

    def test_unique_worker_weekday_schedule(self):
        worker = WorkerFactory()
        WorkScheduleFactory(worker=worker, weekday=Weekday.MONDAY)

        duplicate = WorkScheduleFactory.build(worker=worker, weekday=Weekday.MONDAY)
        with pytest.raises(IntegrityError):
            duplicate.save()


@pytest.mark.django_db
class TestScheduleExceptionModel:
    def test_valid_absence_exception(self):
        worker = WorkerFactory()
        exc = ScheduleException(
            worker=worker,
            date=datetime.date(2026, 11, 1),
            kind=ExceptionKind.ABSENCE,
            start_time=None,
            end_time=None,
            break_start=None,
            break_end=None,
            reason="Vacaciones",
        )
        exc.full_clean()
        exc.save()
        assert exc.pk is not None

    def test_valid_special_hours_exception(self):
        worker = WorkerFactory()
        exc = ScheduleException(
            worker=worker,
            date=datetime.date(2026, 11, 2),
            kind=ExceptionKind.SPECIAL_HOURS,
            start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0),
            break_start=None,
            break_end=None,
            reason="Turno especial matutino",
        )
        exc.full_clean()
        exc.save()
        assert exc.pk is not None

    def test_absence_with_hours_rejected(self):
        worker = WorkerFactory()
        exc = ScheduleException(
            worker=worker,
            date=datetime.date(2026, 11, 3),
            kind=ExceptionKind.ABSENCE,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        with pytest.raises(ValidationError):
            exc.full_clean()

        with pytest.raises(IntegrityError):
            ScheduleException.objects.create(
                worker=worker,
                date=datetime.date(2026, 11, 3),
                kind=ExceptionKind.ABSENCE,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0),
            )

    def test_special_hours_without_hours_rejected(self):
        worker = WorkerFactory()
        exc = ScheduleException(
            worker=worker,
            date=datetime.date(2026, 11, 4),
            kind=ExceptionKind.SPECIAL_HOURS,
            start_time=None,
            end_time=None,
        )
        with pytest.raises(ValidationError):
            exc.full_clean()

        with pytest.raises(IntegrityError):
            ScheduleException.objects.create(
                worker=worker,
                date=datetime.date(2026, 11, 4),
                kind=ExceptionKind.SPECIAL_HOURS,
                start_time=None,
                end_time=None,
            )

    def test_unique_worker_date_exception(self):
        worker = WorkerFactory()
        date = datetime.date(2026, 11, 5)
        ScheduleException.objects.create(
            worker=worker,
            date=date,
            kind=ExceptionKind.ABSENCE,
        )

        with pytest.raises(IntegrityError):
            ScheduleException.objects.create(
                worker=worker,
                date=date,
                kind=ExceptionKind.SPECIAL_HOURS,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(12, 0),
            )


@pytest.mark.django_db
class TestDayConfigModel:
    def test_valid_weekday_config(self):
        cfg = DayConfigFactory.build(weekday=Weekday.MONDAY, date=None, max_appointments=25)
        cfg.full_clean()
        cfg.save()
        assert cfg.pk is not None

    def test_valid_date_override_config(self):
        cfg = DayConfig(
            date=datetime.date(2026, 12, 25),
            weekday=None,
            is_open=False,
            max_appointments=0,
        )
        cfg.full_clean()
        cfg.save()
        assert cfg.pk is not None

    def test_max_appointments_zero_and_none_accepted(self):
        cfg0 = DayConfig(weekday=Weekday.SATURDAY, max_appointments=0, is_open=False)
        cfg0.full_clean()
        cfg0.save()
        assert cfg0.max_appointments == 0

        cfg_none = DayConfig(weekday=Weekday.SUNDAY, max_appointments=None, is_open=True)
        cfg_none.full_clean()
        cfg_none.save()
        assert cfg_none.max_appointments is None

    def test_neither_weekday_nor_date_rejected(self):
        cfg = DayConfig(weekday=None, date=None)
        with pytest.raises(ValidationError):
            cfg.full_clean()

        with pytest.raises(IntegrityError):
            DayConfig.objects.create(weekday=None, date=None)

    def test_both_weekday_and_date_rejected(self):
        cfg = DayConfig(weekday=Weekday.MONDAY, date=datetime.date(2026, 10, 10))
        with pytest.raises(ValidationError):
            cfg.full_clean()

        with pytest.raises(IntegrityError):
            DayConfig.objects.create(weekday=Weekday.MONDAY, date=datetime.date(2026, 10, 10))

    def test_duplicate_weekday_rejected(self):
        DayConfig.objects.create(weekday=Weekday.TUESDAY, max_appointments=10)
        with pytest.raises(IntegrityError):
            DayConfig.objects.create(weekday=Weekday.TUESDAY, max_appointments=15)

    def test_duplicate_date_rejected(self):
        target_date = datetime.date(2026, 10, 20)
        DayConfig.objects.create(date=target_date, max_appointments=10)
        with pytest.raises(IntegrityError):
            DayConfig.objects.create(date=target_date, max_appointments=15)


class TestAdminPermissions:
    def test_hard_delete_disabled_for_catalogs(self):
        site = AdminSite()
        factory = RequestFactory()
        request = factory.get("/admin/")

        worker_admin = WorkerAdmin(Worker, site)
        service_admin = ServiceAdmin(Service, site)
        requester_admin = RequesterAdmin(Requester, site)

        assert worker_admin.has_delete_permission(request) is False
        assert service_admin.has_delete_permission(request) is False
        assert requester_admin.has_delete_permission(request) is False

    def test_day_config_admin_scope_display(self):
        site = AdminSite()
        admin_instance = DayConfigAdmin(DayConfig, site)

        cfg_date = DayConfig(date=datetime.date(2026, 10, 12))
        assert "2026-10-12" in admin_instance.scope_display(cfg_date)

        cfg_weekday = DayConfig(weekday=Weekday.MONDAY)
        assert "Lunes" in admin_instance.scope_display(cfg_weekday)
