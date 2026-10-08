"""Requester admin registration."""

from django.contrib import admin
from django.http import HttpRequest

from agenda.models import Requester


@admin.register(Requester)
class RequesterAdmin(admin.ModelAdmin):
    """Admin interface for managing appointment requesters."""

    list_display = ("full_name", "phone", "email", "anonymized_at", "created_at")
    list_filter = ("anonymized_at",)
    search_fields = ("full_name", "phone", "email")
    readonly_fields = ("anonymized_at",)

    def has_delete_permission(self, request: HttpRequest, obj: Requester | None = None) -> bool:
        """Disallow physical deletion of requesters."""
        return False
