"""Model factories for testing agenda app."""

import datetime
from zoneinfo import ZoneInfo

import factory
from django.conf import settings
from django.contrib.auth.models import User
from factory.django import DjangoModelFactory

from agenda.constants import AppointmentStatus
from agenda.models import (
    Appointment,
    AppointmentEvent,
    DayConfig,
    ExceptionKind,
    Requester,
    ScheduleException,
    Service,
    Weekday,
    Worker,
    WorkSchedule,
)
from agenda.services.manage_token import issue_manage_token


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user_{n}")
    email = factory.Sequence(lambda n: f"user_{n}@example.com")
    is_active = True
    is_staff = False
    is_superuser = False

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "password123")
        user = super()._create(model_class, *args, **kwargs)
        user.set_password(password)
        user.save()
        return user


class StaffUserFactory(UserFactory):
    is_staff = True


class SuperUserFactory(UserFactory):
    is_staff = True
    is_superuser = True


class RequesterFactory(DjangoModelFactory):
    class Meta:
        model = Requester

    full_name = factory.Sequence(lambda n: f"Solicitante {n}")
    phone = "5551234567"
    email = factory.Sequence(lambda n: f"user{n}@example.com")


class ServiceFactory(DjangoModelFactory):
    class Meta:
        model = Service

    name = factory.Sequence(lambda n: f"Servicio {n}")
    description = "Descripción del servicio"
    duration_minutes = 30
    is_active = True


class WorkerFactory(DjangoModelFactory):
    class Meta:
        model = Worker

    user = None
    full_name = factory.Sequence(lambda n: f"Trabajador {n}")
    is_active = True


class WorkerUserFactory(UserFactory):
    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        user = super()._create(model_class, *args, **kwargs)
        if not hasattr(user, "worker_profile"):
            WorkerFactory(user=user, full_name=f"Worker {user.username}")
        return user


class WorkScheduleFactory(DjangoModelFactory):
    class Meta:
        model = WorkSchedule

    worker = factory.SubFactory(WorkerFactory)
    weekday = Weekday.MONDAY
    start_time = datetime.time(9, 0)
    end_time = datetime.time(17, 0)
    break_start = None
    break_end = None


class ScheduleExceptionFactory(DjangoModelFactory):
    class Meta:
        model = ScheduleException

    worker = factory.SubFactory(WorkerFactory)
    date = factory.LazyFunction(datetime.date.today)
    kind = ExceptionKind.ABSENCE
    start_time = None
    end_time = None
    break_start = None
    break_end = None
    reason = "Motivo de ausencia"


class DayConfigFactory(DjangoModelFactory):
    class Meta:
        model = DayConfig

    weekday = Weekday.MONDAY
    date = None
    max_appointments = 20
    is_open = True
    note = "Configuración por defecto"


class AppointmentFactory(DjangoModelFactory):
    class Meta:
        model = Appointment

    requester = factory.SubFactory(RequesterFactory)
    service = factory.SubFactory(ServiceFactory)

    @factory.lazy_attribute
    def worker(self):
        if self.status == AppointmentStatus.WAITLISTED:
            return None
        return WorkerFactory()

    date = factory.LazyFunction(datetime.date.today)

    @factory.lazy_attribute
    def start_at(self):
        tz = ZoneInfo(settings.TIME_ZONE)
        target_date = self.date or datetime.date.today()
        return datetime.datetime.combine(target_date, datetime.time(9, 0), tzinfo=tz)

    @factory.lazy_attribute
    def end_at(self):
        duration = self.service.duration_minutes if self.service else 30
        return self.start_at + datetime.timedelta(minutes=duration)

    status = AppointmentStatus.CONFIRMED


def create_appointment_with_token(**kwargs) -> tuple[Appointment, str]:
    """Helper to create an appointment and issue its initial manage token."""
    appointment = AppointmentFactory(**kwargs)
    raw_token = issue_manage_token(appointment)
    return appointment, raw_token


class AppointmentEventFactory(DjangoModelFactory):
    class Meta:
        model = AppointmentEvent

    appointment = factory.SubFactory(AppointmentFactory)
    from_status = ""
    to_status = AppointmentStatus.CONFIRMED
    worker = factory.LazyAttribute(lambda o: o.appointment.worker)
    actor = None
    note = "Evento de prueba"
