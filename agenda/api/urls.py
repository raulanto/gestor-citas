"""URL configuration for agenda API."""

from django.urls import path

from agenda.api.views import (
    AppointmentCancelView,
    AppointmentCompleteView,
    AppointmentDetailView,
    AppointmentNoShowView,
    AppointmentRescheduleView,
    AppointmentsView,
    AvailabilityView,
    DayConfigDateView,
    DayConfigWeekdayView,
    HealthCheckView,
    WaitlistView,
    WorkerDetailView,
    WorkerExceptionDetailView,
    WorkerExceptionsView,
    WorkerScheduleView,
)

app_name = "agenda"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("availability/", AvailabilityView.as_view(), name="availability"),
    path("appointments/", AppointmentsView.as_view(), name="appointments"),
    path("appointments/<uuid:id>/", AppointmentDetailView.as_view(), name="appointment_detail"),
    path(
        "appointments/<uuid:id>/cancel/",
        AppointmentCancelView.as_view(),
        name="appointment_cancel",
    ),
    path(
        "appointments/<uuid:id>/reschedule/",
        AppointmentRescheduleView.as_view(),
        name="appointment_reschedule",
    ),
    path(
        "appointments/<uuid:id>/complete/",
        AppointmentCompleteView.as_view(),
        name="appointment_complete",
    ),
    path(
        "appointments/<uuid:id>/no-show/",
        AppointmentNoShowView.as_view(),
        name="appointment_no_show",
    ),
    path("waitlist/", WaitlistView.as_view(), name="waitlist"),
    path("workers/<int:id>/schedule/", WorkerScheduleView.as_view(), name="worker_schedule"),
    path("workers/<int:id>/exceptions/", WorkerExceptionsView.as_view(), name="worker_exceptions"),
    path(
        "workers/<int:id>/exceptions/<int:exception_id>/",
        WorkerExceptionDetailView.as_view(),
        name="worker_exception_detail",
    ),
    path("workers/<int:id>/", WorkerDetailView.as_view(), name="worker_detail"),
    path("day-configs/<str:date>/", DayConfigDateView.as_view(), name="day_config_date"),
    path(
        "day-configs/weekday/<int:weekday>/",
        DayConfigWeekdayView.as_view(),
        name="day_config_weekday",
    ),
]
