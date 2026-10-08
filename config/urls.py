"""Main URL configuration for agenda-citas project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api-auth/", include("rest_framework.urls")),  # <- Login/Logout en la esquina superior
    path("api/v1/", include("agenda.api.urls")),
]
