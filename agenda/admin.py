"""Django admin registration for agenda models."""

from django.contrib import admin, messages
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
from agenda.selectors import list_active_appointments
from agenda.selectors.waitlist import waitlist_position
from agenda.services import (
    cancel_appointment,
    complete_appointment,
    mark_no_show,
    process_waitlist,
    revalidate_worker,
    schedule_waitlist_processing,
)


def _get_request_actor(request: HttpRequest):
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return user
    return None


def _handle_worker_revalidation_message(request: HttpRequest, result) -> None:
    if result.displaced or result.over_quota or result.unserviceable:
        details = []
        if result.reassigned:
            details.append(f"reasignadas: {result.reassigned}")
        if result.waitlisted:
            details.append(f"enviadas a espera: {result.waitlisted}")
        if result.unserviceable:
            details.append(f"inatendibles: {result.unserviceable}")
        if result.over_quota:
            details.append(f"fechas en sobrecupo: {', '.join(result.over_quota)}")

        msg = f"Aviso de revalidación de horario: {', '.join(details)}."
        messages.warning(request, msg)


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


@admin.register(Worker)
class WorkerAdmin(WaitlistTriggerMixin, admin.ModelAdmin):
    """Admin interface for managing staff workers."""

    list_display = ("full_name", "user", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("full_name", "user__username", "user__email")
    inlines = [WorkScheduleInline, ScheduleExceptionInline]

    def save_model(self, request: HttpRequest, obj: Worker, form, change) -> None:
        super().save_model(request, obj, form, change)
        result = revalidate_worker(obj.id, actor=_get_request_actor(request))
        _handle_worker_revalidation_message(request, result)

    def save_formset(self, request: HttpRequest, form, formset, change) -> None:
        super().save_formset(request, form, formset, change)
        if form.instance and isinstance(form.instance, Worker):
            result = revalidate_worker(form.instance.id, actor=_get_request_actor(request))
            _handle_worker_revalidation_message(request, result)

    def has_delete_permission(self, request: HttpRequest, obj: Worker | None = None) -> bool:
        """Disallow physical deletion of workers (deactivate via is_active instead)."""
        return False


@admin.register(WorkSchedule)
class WorkScheduleAdmin(WaitlistTriggerMixin, admin.ModelAdmin):
    """Admin interface for managing individual work schedule entries."""

    list_display = ("worker", "weekday", "start_time", "end_time", "break_start", "break_end")
    list_filter = ("weekday", "worker")

    def save_model(self, request: HttpRequest, obj: WorkSchedule, form, change) -> None:
        super().save_model(request, obj, form, change)
        result = revalidate_worker(obj.worker_id, actor=_get_request_actor(request))
        _handle_worker_revalidation_message(request, result)

    def delete_model(self, request: HttpRequest, obj: WorkSchedule) -> None:
        worker_id = obj.worker_id
        super().delete_model(request, obj)
        result = revalidate_worker(worker_id, actor=_get_request_actor(request))
        _handle_worker_revalidation_message(request, result)


@admin.register(ScheduleException)
class ScheduleExceptionAdmin(WaitlistTriggerMixin, admin.ModelAdmin):
    """Admin interface for managing schedule exceptions."""

    list_display = ("worker", "date", "kind", "start_time", "end_time", "reason")
    list_filter = ("kind", "date", "worker")

    def save_model(self, request: HttpRequest, obj: ScheduleException, form, change) -> None:
        super().save_model(request, obj, form, change)
        result = revalidate_worker(obj.worker_id, actor=_get_request_actor(request))
        _handle_worker_revalidation_message(request, result)

    def delete_model(self, request: HttpRequest, obj: ScheduleException) -> None:
        worker_id = obj.worker_id
        super().delete_model(request, obj)
        result = revalidate_worker(worker_id, actor=_get_request_actor(request))
        _handle_worker_revalidation_message(request, result)


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
