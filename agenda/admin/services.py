"""Service admin registration."""

from django.contrib import admin
from django.http import HttpRequest

from agenda.models import Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    """Admin interface for managing appointment services."""

    list_display = ("name", "duration_minutes", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")

    def has_delete_permission(self, request: HttpRequest, obj: Service | None = None) -> bool:
        """Disallow physical deletion of services (deactivate via is_active instead)."""
        return False
