"""Views package for agenda API."""

from .appointments import (
    AppointmentCancelView,
    AppointmentCompleteView,
    AppointmentCreateView,
    AppointmentDetailView,
    AppointmentListView,
    AppointmentNoShowView,
    AppointmentRescheduleView,
    AppointmentRotateTokenView,
    AppointmentsView,
)
from .availability import AvailabilityView
from .day_configs import DayConfigDateView, DayConfigWeekdayView
from .schedules import (
    WorkerExceptionDetailView,
    WorkerExceptionsView,
    WorkerScheduleView,
)
from .waitlist import WaitlistView
from .worker_agenda import WorkerAgendaView
from .workers import WorkerDetailView

__all__ = [
    "AppointmentCancelView",
    "AppointmentCompleteView",
    "AppointmentCreateView",
    "AppointmentDetailView",
    "AppointmentListView",
    "AppointmentNoShowView",
    "AppointmentRescheduleView",
    "AppointmentRotateTokenView",
    "AppointmentsView",
    "AvailabilityView",
    "DayConfigDateView",
    "DayConfigWeekdayView",
    "WaitlistView",
    "WorkerAgendaView",
    "WorkerDetailView",
    "WorkerExceptionDetailView",
    "WorkerExceptionsView",
    "WorkerScheduleView",
]
