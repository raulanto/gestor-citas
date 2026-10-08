"""Serializers package for agenda API endpoints."""

from .appointments import (
    AppointmentBookingResponseSerializer,
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentDetailSerializer,
    AppointmentListQuerySerializer,
    AppointmentRescheduleSerializer,
    BaseAppointmentDetailSerializer,
    RequesterAppointmentDetailSerializer,
    RotateTokenResponseSerializer,
    StaffAppointmentDetailSerializer,
    WorkerAppointmentDetailSerializer,
)
from .availability import (
    AvailabilityQuerySerializer,
    DayAvailabilitySerializer,
    ServiceSummarySerializer,
    SlotSerializer,
)
from .day_configs import (
    DayConfigDetailSerializer,
    DayConfigSummaryResponseSerializer,
    DayConfigUpdateSerializer,
)
from .requesters import (
    RequesterDetailSerializer,
    RequesterInputSerializer,
    RequesterPublicDetailSerializer,
    RequesterWorkerDetailSerializer,
)
from .schedules import (
    ScheduleChangeResponseSerializer,
    ScheduleExceptionCreateSerializer,
    ScheduleExceptionDetailSerializer,
    WorkerPatchSerializer,
    WorkerScheduleDetailSerializer,
    WorkScheduleDetailSerializer,
    WorkScheduleEntrySerializer,
    WorkScheduleSetSerializer,
)
from .waitlist import (
    WaitlistEntrySerializer,
    WaitlistQuerySerializer,
)
from .worker_agenda import (
    WorkerAgendaAppointmentSerializer,
    WorkerAgendaQuerySerializer,
)

__all__ = [
    "AppointmentBookingResponseSerializer",
    "AppointmentCancelSerializer",
    "AppointmentCreateSerializer",
    "AppointmentDetailSerializer",
    "AppointmentListQuerySerializer",
    "AppointmentRescheduleSerializer",
    "AvailabilityQuerySerializer",
    "BaseAppointmentDetailSerializer",
    "DayAvailabilitySerializer",
    "DayConfigDetailSerializer",
    "DayConfigSummaryResponseSerializer",
    "DayConfigUpdateSerializer",
    "RequesterAppointmentDetailSerializer",
    "RequesterDetailSerializer",
    "RequesterInputSerializer",
    "RequesterPublicDetailSerializer",
    "RequesterWorkerDetailSerializer",
    "RotateTokenResponseSerializer",
    "ScheduleChangeResponseSerializer",
    "ScheduleExceptionCreateSerializer",
    "ScheduleExceptionDetailSerializer",
    "ServiceSummarySerializer",
    "SlotSerializer",
    "StaffAppointmentDetailSerializer",
    "WaitlistEntrySerializer",
    "WaitlistQuerySerializer",
    "WorkScheduleDetailSerializer",
    "WorkScheduleEntrySerializer",
    "WorkScheduleSetSerializer",
    "WorkerAgendaAppointmentSerializer",
    "WorkerAgendaQuerySerializer",
    "WorkerAppointmentDetailSerializer",
    "WorkerPatchSerializer",
    "WorkerScheduleDetailSerializer",
]
