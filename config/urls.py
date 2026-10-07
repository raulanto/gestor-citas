"""Main URL configuration for agenda-citas project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("agenda.api.urls")),
]
