"""Pure capacity and slot generation calculations for worker shifts and daily quotas.

This module is strictly stateless and contains NO database access or model imports.
"""

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

from agenda.selectors.types import Shift


@dataclass(frozen=True)
class Interval:
    """Immutable time interval [start, end) on a 24-hour clock within a single day."""

    start: datetime.time
    end: datetime.time

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(
                f"Invalid interval: start ({self.start}) must be before end ({self.end})."
            )

    @property
    def duration_minutes(self) -> int:
        """Calculate total duration of the interval in minutes."""
        return (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)

    def overlaps(self, other: "Interval") -> bool:
        """Check if two semi-open intervals [start, end) overlap.

        Touching at the boundary (e.g. [09:00, 10:00) and [10:00, 11:00)) does NOT overlap.
        """
        return max(self.start, other.start) < min(self.end, other.end)


def work_segments(shift: Shift) -> list[Interval]:
    """Split a shift into continuous working intervals according to its break."""
    if shift.break_start is None or shift.break_end is None:
        return [Interval(start=shift.start, end=shift.end)]

    segments: list[Interval] = []
    if shift.start < shift.break_start:
        segments.append(Interval(start=shift.start, end=shift.break_start))
    if shift.break_end < shift.end:
        segments.append(Interval(start=shift.break_end, end=shift.end))

    return segments


def worker_capacity(shift: Shift, duration_minutes: int) -> int:
    """Calculate maximum non-overlapping appointments a worker can attend during a shift.

    Appointments cannot cross breaks. Capacity is calculated as the sum of
    floor(segment_minutes / duration_minutes) for each continuous work segment.
    """
    if duration_minutes <= 0:
        return 0

    return sum(segment.duration_minutes // duration_minutes for segment in work_segments(shift))


def generate_slots(
    shift: Shift,
    duration_minutes: int,
    step_minutes: int,
) -> list[Interval]:
    """Generate available appointment slot intervals every `step_minutes`.

    Each slot interval [start, end) must fit entirely inside a single continuous work segment.
    """
    if duration_minutes <= 0 or step_minutes <= 0:
        return []

    slots: list[Interval] = []
    for segment in work_segments(shift):
        seg_start_minutes = segment.start.hour * 60 + segment.start.minute
        seg_end_minutes = segment.end.hour * 60 + segment.end.minute

        curr_min = seg_start_minutes
        while curr_min + duration_minutes <= seg_end_minutes:
            slot_start = datetime.time(curr_min // 60, curr_min % 60)
            slot_end_min = curr_min + duration_minutes
            slot_end = datetime.time(slot_end_min // 60, slot_end_min % 60)
            slots.append(Interval(start=slot_start, end=slot_end))
            curr_min += step_minutes

    return slots


def personnel_capacity(shifts: Iterable[Shift], duration_minutes: int) -> int:
    """Calculate the aggregate non-overlapping capacity of a collection of worker shifts."""
    return sum(worker_capacity(shift, duration_minutes) for shift in shifts)


def effective_quota(max_appointments: int | None, personnel_capacity: int) -> int:
    """Calculate the effective quota of appointments for a day.

    Effective quota is the minimum between DayConfig.max_appointments (if set)
    and the aggregate personnel capacity.
    """
    if max_appointments is None:
        return personnel_capacity
    return min(max_appointments, personnel_capacity)
