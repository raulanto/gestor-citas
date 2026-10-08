"""Mixins and helper utilities for Django admin."""

from django.contrib import messages
from django.http import HttpRequest

from agenda.services import schedule_waitlist_processing


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
