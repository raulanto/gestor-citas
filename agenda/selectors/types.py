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
