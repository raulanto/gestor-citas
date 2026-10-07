"""URL configuration for agenda API."""

from django.urls import path

from agenda.api.views import HealthCheckView

app_name = "agenda"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
]
