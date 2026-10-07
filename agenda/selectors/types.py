"""Dataclasses representing resolved scheduling and configuration entities."""

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Shift:
    """Immutable representation of a resolved working shift."""

    start: datetime.time
    end: datetime.time
    break_start: datetime.time | None = None
    break_end: datetime.time | None = None


@dataclass(frozen=True)
class DayConfigResolved:
    """Immutable representation of a resolved day configuration."""

    date: datetime.date
    is_open: bool
    max_appointments: int | None
    source: str  # "date_override" | "weekday_default" | "fallback"
