"""Django admin registration for agenda models."""

from django.contrib import admin
from django.http import HttpRequest

from agenda.models import (
    Appointment,
    AppointmentEvent,
    DayConfig,
    Requester,
    ScheduleException,
    Service,
    Worker,
    WorkSchedule,
)


class WorkScheduleInline(admin.TabularInline):
    """Inline editor for a worker's weekly work schedule."""

    model = WorkSchedule
    extra = 0
    max_num = 7
    fields = ("weekday", "start_time", "end_time", "break_start", "break_end")


class ScheduleExceptionInline(admin.TabularInline):
    """Inline editor for a worker's date exceptions (absences and special hours)."""

    model = ScheduleException
    extra = 0
    fields = ("date", "kind", "start_time", "end_time", "break_start", "break_end", "reason")


class AppointmentEventInline(admin.TabularInline):
    """Read-only inline display of audit events for an appointment."""

    model = AppointmentEvent
    extra = 0
    can_delete = False
    readonly_fields = ("from_status", "to_status", "worker", "actor", "note", "created_at")

    def has_add_permission(self, request: HttpRequest, obj: Appointment | None = None) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: AppointmentEvent | None = None
    ) -> bool:
        return False


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    """Read-only admin interface for viewing appointments and their audit history."""

    list_display = (
        "id",
        "requester",
        "service",
        "worker",
        "date",
        "start_at",
        "end_at",
        "status",
        "created_at",
    )
    list_filter = ("status", "date", "worker", "service")
    search_fields = ("requester__full_name", "requester__phone", "requester__email", "id")
    readonly_fields = (
        "id",
        "requester",
        "service",
        "worker",
        "date",
        "start_at",
        "end_at",
        "status",
        "rescheduled_from",
        "created_at",
        "updated_at",
    )
    inlines = [AppointmentEventInline]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Appointment | None = None) -> bool:
        return False


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    """Admin interface for managing staff workers."""

    list_display = ("full_name", "user", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("full_name", "user__username", "user__email")
    inlines = [WorkScheduleInline, ScheduleExceptionInline]

    def has_delete_permission(self, request: HttpRequest, obj: Worker | None = None) -> bool:
        """Disallow physical deletion of workers (deactivate via is_active instead)."""
        return False


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    """Admin interface for managing appointment services."""

    list_display = ("name", "duration_minutes", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")

    def has_delete_permission(self, request: HttpRequest, obj: Service | None = None) -> bool:
        """Disallow physical deletion of services (deactivate via is_active instead)."""
        return False


@admin.register(Requester)
class RequesterAdmin(admin.ModelAdmin):
    """Admin interface for managing appointment requesters."""

    list_display = ("full_name", "phone", "email", "created_at")
    search_fields = ("full_name", "phone", "email")

    def has_delete_permission(self, request: HttpRequest, obj: Requester | None = None) -> bool:
        """Disallow physical deletion of requesters."""
        return False


@admin.register(DayConfig)
class DayConfigAdmin(admin.ModelAdmin):
    """Admin interface for managing day capacity and open/closed configurations."""

    list_display = ("scope_display", "is_open", "max_appointments", "note", "updated_at")
    list_filter = ("is_open", "weekday")
    search_fields = ("note",)

    @admin.display(description="Alcance (Día / Fecha)")
    def scope_display(self, obj: DayConfig) -> str:
        if obj.date is not None:
            return f"Fecha específica: {obj.date}"
        elif obj.weekday is not None:
            return f"Día semanal: {obj.get_weekday_display()}"
        return "Sin definir"
