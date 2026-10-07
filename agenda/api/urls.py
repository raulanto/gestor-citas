"""URL configuration for agenda API."""

from django.urls import path

from agenda.api.views import AvailabilityView, HealthCheckView

app_name = "agenda"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("availability/", AvailabilityView.as_view(), name="availability"),
]
