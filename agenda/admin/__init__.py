"""Django admin package for agenda models."""

from agenda.admin.appointments import AppointmentAdmin, AppointmentEventInline
from agenda.admin.day_configs import DayConfigAdmin
from agenda.admin.mixins import WaitlistTriggerMixin
from agenda.admin.requesters import RequesterAdmin
from agenda.admin.services import ServiceAdmin
from agenda.admin.workers import (
    ScheduleExceptionAdmin,
    ScheduleExceptionInline,
    WorkerAdmin,
    WorkScheduleAdmin,
    WorkScheduleInline,
)

__all__ = [
    "AppointmentAdmin",
    "AppointmentEventInline",
    "DayConfigAdmin",
    "RequesterAdmin",
    "ScheduleExceptionAdmin",
    "ScheduleExceptionInline",
    "ServiceAdmin",
    "WaitlistTriggerMixin",
    "WorkerAdmin",
    "WorkScheduleAdmin",
    "WorkScheduleInline",
]
