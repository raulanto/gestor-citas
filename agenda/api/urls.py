"""URL configuration for agenda API."""

from django.urls import path

from agenda.api.views import (
    AppointmentCreateView,
    AppointmentDetailView,
    AvailabilityView,
    HealthCheckView,
)

app_name = "agenda"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("availability/", AvailabilityView.as_view(), name="availability"),
    path("appointments/", AppointmentCreateView.as_view(), name="appointment_create"),
    path("appointments/<uuid:id>/", AppointmentDetailView.as_view(), name="appointment_detail"),
]
