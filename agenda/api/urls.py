"""URL configuration for agenda API."""

from django.conf import settings
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from agenda.api.auth.views import LoginView, LogoutView, MeView, TokenRefreshCustomView
from agenda.api.health import HealthCheckView, HealthReadyView
from agenda.api.views import (
    AppointmentCancelView,
    AppointmentCompleteView,
    AppointmentDetailView,
    AppointmentNoShowView,
    AppointmentRescheduleView,
    AppointmentRotateTokenView,
    AppointmentsView,
    AvailabilityView,
    DayConfigDateView,
    DayConfigWeekdayView,
    WaitlistView,
    WorkerAgendaView,
    WorkerDetailView,
    WorkerExceptionDetailView,
    WorkerExceptionsView,
    WorkerScheduleView,
)

app_name = "agenda"

router = DefaultRouter()

urlpatterns = [
    # Public & Health
    path("health/", HealthCheckView.as_view(), name="health"),
    path("health/ready/", HealthReadyView.as_view(), name="health_ready"),
    path("availability/", AvailabilityView.as_view(), name="availability"),
    # Auth endpoints
    path("auth/token/", LoginView.as_view(), name="auth_token"),
    path("auth/token/refresh/", TokenRefreshCustomView.as_view(), name="auth_token_refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth_logout"),
    path("auth/me/", MeView.as_view(), name="auth_me"),
    # Appointments
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
    path(
        "appointments/<uuid:id>/token/",
        AppointmentRotateTokenView.as_view(),
        name="appointment_rotate_token",
    ),
    # Waitlist & Agenda
    path("waitlist/", WaitlistView.as_view(), name="waitlist"),
    path("me/agenda/", WorkerAgendaView.as_view(), name="worker_agenda"),
    # Workers & Schedules
    path("workers/<int:id>/schedule/", WorkerScheduleView.as_view(), name="worker_schedule"),
    path("workers/<int:id>/exceptions/", WorkerExceptionsView.as_view(), name="worker_exceptions"),
    path(
        "workers/<int:id>/exceptions/<int:exception_id>/",
        WorkerExceptionDetailView.as_view(),
        name="worker_exception_detail",
    ),
    path("workers/<int:id>/", WorkerDetailView.as_view(), name="worker_detail"),
    # Day Configurations
    path("day-configs/<str:date>/", DayConfigDateView.as_view(), name="day_config_date"),
    path(
        "day-configs/weekday/<int:weekday>/",
        DayConfigWeekdayView.as_view(),
        name="day_config_weekday",
    ),
] + router.urls

if getattr(settings, "API_DOCS_ENABLED", True):
    urlpatterns += [
        path("schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "docs/",
            SpectacularSwaggerView.as_view(url_name="agenda:schema"),
            name="swagger_ui",
        ),
    ]
