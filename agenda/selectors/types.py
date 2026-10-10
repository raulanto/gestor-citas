"""Dataclasses representing resolved scheduling and configuration entities."""

import datetime
from dataclasses import dataclass

from agenda.services.capacity import Shift

__all__ = ["DayConfigResolved", "Shift"]


@dataclass(frozen=True)
class DayConfigResolved:
    """Immutable representation of a resolved day configuration."""

    date: datetime.date
    is_open: bool
    max_appointments: int | None
    source: str  # "date_override" | "weekday_default" | "fallback"
    booking_min_advance_hours: int = 2
    booking_max_advance_days: int = 60
    cancel_min_hours: int = 4
    max_reschedules_per_appointment: int = 2
    max_active_per_requester_per_day: int = 1
    waitlist_max_per_day: int = 20
    default_slot_step_minutes: int = 15
