"""Model factories for testing agenda app."""

import datetime
from zoneinfo import ZoneInfo

import factory
from django.conf import settings
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

    full_name = factory.Sequence(lambda n: f"Trabajador {n}")
    is_active = True


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
    worker = factory.SubFactory(WorkerFactory)
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


class AppointmentEventFactory(DjangoModelFactory):
    class Meta:
        model = AppointmentEvent

    appointment = factory.SubFactory(AppointmentFactory)
    from_status = ""
    to_status = AppointmentStatus.CONFIRMED
    worker = factory.LazyAttribute(lambda o: o.appointment.worker)
    actor = None
    note = "Evento de prueba"
