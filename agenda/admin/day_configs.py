"""DayConfig admin registration."""

from django.contrib import admin, messages
from django.http import HttpRequest

from agenda.admin.mixins import WaitlistTriggerMixin
from agenda.models import DayConfig
from agenda.selectors import list_active_appointments


@admin.register(DayConfig)
class DayConfigAdmin(WaitlistTriggerMixin, admin.ModelAdmin):
    """Admin interface for managing day capacity and open/closed configurations."""

    list_display = ("scope_display", "is_open", "max_appointments", "note", "updated_at")
    list_filter = ("is_open", "weekday")
    search_fields = ("note",)

    def save_model(self, request: HttpRequest, obj: DayConfig, form, change) -> None:
        super().save_model(request, obj, form, change)
        if not obj.is_open and obj.date:
            active_appts = list_active_appointments(obj.date)
            if active_appts:
                self.message_user(
                    request,
                    (
                        f"Atención: existen {len(active_appts)} citas activas para la fecha "
                        f"{obj.date} que deben reprogramarse o cancelarse."
                    ),
                    level=messages.WARNING,
                )

    @admin.display(description="Alcance (Día / Fecha)")
    def scope_display(self, obj: DayConfig) -> str:
        if obj.date is not None:
            return f"Fecha específica: {obj.date}"
        elif obj.weekday is not None:
            return f"Día semanal: {obj.get_weekday_display()}"
        return "Sin definir"
