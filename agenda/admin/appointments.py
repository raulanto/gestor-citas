"""Appointment admin and inline audit events."""

from django.contrib import admin, messages
from django.http import HttpRequest

from agenda.constants import AppointmentStatus
from agenda.models import Appointment, AppointmentEvent
from agenda.selectors.waitlist import waitlist_position
from agenda.services import (
    cancel_appointment,
    complete_appointment,
    mark_no_show,
    process_waitlist,
)


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
        "reschedule_count",
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
        "reschedule_count",
        "rescheduled_from",
        "rescheduled_to_display",
        "created_at",
        "updated_at",
    )
    inlines = [AppointmentEventInline]
    actions = [
        "reprocess_waitlist_action",
        "cancel_selected_forced_action",
        "complete_selected_action",
        "mark_no_show_selected_action",
    ]

    @admin.display(description="Posición en espera")
    def waitlist_position_display(self, obj: Appointment) -> str:
        if obj.status == AppointmentStatus.WAITLISTED:
            pos = waitlist_position(obj)
            return f"#{pos}" if pos else "-"
        return "-"

    @admin.display(description="Reprogramada hacia")
    def rescheduled_to_display(self, obj: Appointment) -> str:
        child = obj.rescheduled_to
        return str(child.id) if child else "-"

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

    @admin.action(description="Cancelar seleccionadas (forzado)")
    def cancel_selected_forced_action(self, request: HttpRequest, queryset) -> None:
        cancelled_count = 0
        for appt in queryset:
            try:
                cancel_appointment(
                    appt,
                    reason="Cancelada forzadamente desde admin.",
                    actor=request.user,
                    force=True,
                )
                cancelled_count += 1
            except Exception as exc:
                self.message_user(
                    request, f"Error al cancelar {appt.id}: {exc}", level=messages.ERROR
                )
        if cancelled_count:
            self.message_user(
                request,
                f"Se cancelaron {cancelled_count} citas forzadamente.",
                level=messages.SUCCESS,
            )

    @admin.action(description="Marcar completadas")
    def complete_selected_action(self, request: HttpRequest, queryset) -> None:
        completed_count = 0
        for appt in queryset:
            try:
                complete_appointment(appt, actor=request.user)
                completed_count += 1
            except Exception as exc:
                self.message_user(
                    request, f"Error al completar {appt.id}: {exc}", level=messages.ERROR
                )
        if completed_count:
            self.message_user(
                request,
                f"Se marcaron como completadas {completed_count} citas.",
                level=messages.SUCCESS,
            )

    @admin.action(description="Marcar inasistencia")
    def mark_no_show_selected_action(self, request: HttpRequest, queryset) -> None:
        no_show_count = 0
        for appt in queryset:
            try:
                mark_no_show(appt, actor=request.user)
                no_show_count += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Error al marcar inasistencia de {appt.id}: {exc}",
                    level=messages.ERROR,
                )
        if no_show_count:
            self.message_user(
                request,
                f"Se registró inasistencia para {no_show_count} citas.",
                level=messages.SUCCESS,
            )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Appointment | None = None) -> bool:
        return False
