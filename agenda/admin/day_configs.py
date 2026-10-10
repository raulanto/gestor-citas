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
    fieldsets = (
        (
            "Alcance y Capacidad",
            {
                "fields": ("weekday", "date", "is_open", "max_appointments", "note"),
            },
        ),
        (
            "Reglas de Reserva y Ventanas",
            {
                "fields": (
                    "booking_min_advance_hours",
                    "booking_max_advance_days",
                    "default_slot_step_minutes",
                ),
                "description": (
                    "Parámetros que controlan cuándo y cómo los usuarios pueden agendar. "
                    "Dejar vacío para heredar la configuración global del sistema."
                ),
            },
        ),
        (
            "Cancelación y Reprogramación",
            {
                "fields": (
                    "cancel_min_hours",
                    "max_reschedules_per_appointment",
                ),
                "description": (
                    "Parámetros que controlan límites de cancelación y reprogramación. "
                    "Dejar vacío para heredar la configuración global del sistema."
                ),
            },
        ),
        (
            "Límites de Solicitantes y Lista de Espera",
            {
                "fields": (
                    "max_active_per_requester_per_day",
                    "waitlist_max_per_day",
                ),
                "description": (
                    "Límites de citas activas por persona y capacidad máxima de espera. "
                    "Dejar vacío para heredar la configuración global del sistema."
                ),
            },
        ),
    )

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
