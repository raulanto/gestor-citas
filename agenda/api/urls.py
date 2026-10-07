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
    HealthCheckView,
    WaitlistView,
)

app_name = "agenda"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("availability/", AvailabilityView.as_view(), name="availability"),
    path("appointments/", AppointmentsView.as_view(), name="appointments"),
    path("appointments/<uuid:id>/", AppointmentDetailView.as_view(), name="appointment_detail"),
    path("appointments/<uuid:id>/cancel/", AppointmentCancelView.as_view(), name="appointment_cancel"),
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
]
