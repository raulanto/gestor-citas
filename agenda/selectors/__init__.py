"""Agenda selectors package for read-only queries."""

from agenda.selectors.appointments import (
    get_appointment,
    list_active_appointments,
    list_appointments_queryset,
    list_worker_agenda,
)
from agenda.selectors.availability import DayAvailability, Slot, get_day_availability
from agenda.selectors.day_configs import resolve_day_config
from agenda.selectors.schedules import (
    DayConfigSummary,
    get_day_config_summary,
    get_worker_schedule,
    list_unserviceable_waitlist,
)
from agenda.selectors.types import DayConfigResolved, Shift
from agenda.selectors.waitlist import (
    WaitlistEntry,
    dates_with_waitlist,
    list_waitlist,
    waitlist_position,
)
from agenda.selectors.workers import list_available_workers_on, resolve_worker_shift

__all__ = [
    "DayAvailability",
    "DayConfigResolved",
    "DayConfigSummary",
    "Shift",
    "Slot",
    "WaitlistEntry",
    "dates_with_waitlist",
    "get_appointment",
    "get_day_availability",
    "get_day_config_summary",
    "get_worker_schedule",
    "list_active_appointments",
    "list_appointments_queryset",
    "list_available_workers_on",
    "list_unserviceable_waitlist",
    "list_waitlist",
    "list_worker_agenda",
    "resolve_day_config",
    "resolve_worker_shift",
    "waitlist_position",
]
