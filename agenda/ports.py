"""Ports defining external interfaces and adapter protocols for agenda microapp."""

import datetime
from collections.abc import Sequence
from typing import Protocol

from agenda.services.capacity import Interval


class BusySlotsPort(Protocol):
    """Protocol for querying busy intervals and active appointment counts for a given date."""

    def busy_intervals(self, target_date: datetime.date) -> dict[int, Sequence[Interval]]:
        """Return a mapping of worker_id -> list of occupied Interval objects on target_date."""
        ...

    def active_count(self, target_date: datetime.date) -> int:
        """Return the count of active appointments on target_date."""
        ...


class NullBusySlots:
    """Default null adapter for Phase 2 before the Appointment model is implemented in Phase 3."""

    def busy_intervals(self, target_date: datetime.date) -> dict[int, Sequence[Interval]]:
        return {}

    def active_count(self, target_date: datetime.date) -> int:
        return 0
