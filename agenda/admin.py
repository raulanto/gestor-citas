"""Django admin registration for agenda models."""

from django.contrib import admin
from django.http import HttpRequest

from agenda.constants import AppointmentStatus
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
from agenda.selectors.waitlist import waitlist_position
from agenda.services.waitlist import process_waitlist, schedule_waitlist_processing


class WaitlistTriggerMixin:
    """Admin mixin that triggers asynchronous waitlist processing on catalog changes."""

    def save_model(self, request: HttpRequest, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        schedule_waitlist_processing()

    def delete_model(self, request: HttpRequest, obj) -> None:
        super().delete_model(request, obj)
        schedule_waitlist_processing()

    def save_formset(self, request: HttpRequest, form, formset, change) -> None:
        super().save_formset(request, form, formset, change)
        schedule_waitlist_processing()

    def delete_queryset(self, request: HttpRequest, queryset) -> None:
        super().delete_queryset(request, queryset)
        schedule_waitlist_processing()


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
        "waitlist_position_display",
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
    actions = ["reprocess_waitlist_action"]

    @admin.display(description="Posición en espera")
    def waitlist_position_display(self, obj: Appointment) -> str:
        if obj.status == AppointmentStatus.WAITLISTED:
            pos = waitlist_position(obj)
            return f"#{pos}" if pos else "-"
        return "-"

    @admin.action(description="Reprocesar lista de espera para fechas seleccionadas")
    def reprocess_waitlist_action(self, request: HttpRequest, queryset) -> None:
        dates = set(queryset.values_list("date", flat=True))
        total_assigned = 0
        for target_date in sorted(dates):
            result = process_waitlist(target_date)
            total_assigned += len(result.assigned)
        self.message_user(
            request,
            f"Se reprocesaron {len(dates)} fechas y se asignaron {total_assigned} citas.",
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Appointment | None = None
    ) -> bool:
        return False


@admin.register(Worker)
class WorkerAdmin(WaitlistTriggerMixin, admin.ModelAdmin):
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
class DayConfigAdmin(WaitlistTriggerMixin, admin.ModelAdmin):
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
