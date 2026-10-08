"""Worker, WorkSchedule, and ScheduleException admin registrations."""

from django.contrib import admin
from django.http import HttpRequest

from agenda.admin.mixins import (
    WaitlistTriggerMixin,
    _get_request_actor,
    _handle_worker_revalidation_message,
)
from agenda.models import ScheduleException, Worker, WorkSchedule
from agenda.services import revalidate_worker


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
