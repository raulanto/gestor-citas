"""Backward-compatibility alias for locks module."""

from agenda.services.locks import (
    APPOINTMENT_BOOKING_LOCK_NAMESPACE,
    acquire_day_advisory_lock,
    day_advisory_lock,
)

__all__ = [
    "APPOINTMENT_BOOKING_LOCK_NAMESPACE",
    "acquire_day_advisory_lock",
    "day_advisory_lock",
]
