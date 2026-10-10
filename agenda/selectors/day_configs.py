"""Selectors for day configuration resolution."""

import datetime

from django.conf import settings

from agenda.models import DayConfig
from agenda.selectors.types import DayConfigResolved


def _resolve_param(
    date_override: DayConfig | None,
    weekday_default: DayConfig | None,
    field_name: str,
    setting_name: str,
    default_val: int,
) -> int:
    """Resolve an integer parameter cascading through date override, weekday, and settings."""
    if date_override is not None:
        val = getattr(date_override, field_name)
        if val is not None:
            return val
    if weekday_default is not None:
        val = getattr(weekday_default, field_name)
        if val is not None:
            return val
    return getattr(settings, setting_name, default_val)


def resolve_day_config(target_date: datetime.date) -> DayConfigResolved:
    """Resolve the effective day configuration for a given date.

    Priority:
    1. Single-date override (DayConfig.date == target_date)
    2. Weekday default (DayConfig.weekday == target_date.weekday())
    3. Fallback default (is_open=True, max_appointments=None, source="fallback")
    """
    date_override = DayConfig.objects.filter(date=target_date).first()
    weekday_default = DayConfig.objects.filter(weekday=target_date.weekday()).first()

    booking_min_advance_hours = _resolve_param(
        date_override, weekday_default, "booking_min_advance_hours", "BOOKING_MIN_ADVANCE_HOURS", 2
    )
    booking_max_advance_days = _resolve_param(
        date_override, weekday_default, "booking_max_advance_days", "BOOKING_MAX_ADVANCE_DAYS", 60
    )
    cancel_min_hours = _resolve_param(
        date_override, weekday_default, "cancel_min_hours", "CANCEL_MIN_HOURS", 4
    )
    max_reschedules_per_appointment = _resolve_param(
        date_override,
        weekday_default,
        "max_reschedules_per_appointment",
        "MAX_RESCHEDULES_PER_APPOINTMENT",
        2,
    )
    max_active_per_requester_per_day = _resolve_param(
        date_override,
        weekday_default,
        "max_active_per_requester_per_day",
        "MAX_ACTIVE_PER_REQUESTER_PER_DAY",
        1,
    )
    waitlist_max_per_day = _resolve_param(
        date_override, weekday_default, "waitlist_max_per_day", "WAITLIST_MAX_PER_DAY", 20
    )
    default_slot_step_minutes = _resolve_param(
        date_override,
        weekday_default,
        "default_slot_step_minutes",
        "DEFAULT_SLOT_STEP_MINUTES",
        15,
    )

    # 1. Date override
    if date_override is not None:
        return DayConfigResolved(
            date=target_date,
            is_open=date_override.is_open,
            max_appointments=date_override.max_appointments,
            source="date_override",
            booking_min_advance_hours=booking_min_advance_hours,
            booking_max_advance_days=booking_max_advance_days,
            cancel_min_hours=cancel_min_hours,
            max_reschedules_per_appointment=max_reschedules_per_appointment,
            max_active_per_requester_per_day=max_active_per_requester_per_day,
            waitlist_max_per_day=waitlist_max_per_day,
            default_slot_step_minutes=default_slot_step_minutes,
        )

    # 2. Weekday default
    if weekday_default is not None:
        return DayConfigResolved(
            date=target_date,
            is_open=weekday_default.is_open,
            max_appointments=weekday_default.max_appointments,
            source="weekday_default",
            booking_min_advance_hours=booking_min_advance_hours,
            booking_max_advance_days=booking_max_advance_days,
            cancel_min_hours=cancel_min_hours,
            max_reschedules_per_appointment=max_reschedules_per_appointment,
            max_active_per_requester_per_day=max_active_per_requester_per_day,
            waitlist_max_per_day=waitlist_max_per_day,
            default_slot_step_minutes=default_slot_step_minutes,
        )

    # 3. Fallback default
    return DayConfigResolved(
        date=target_date,
        is_open=True,
        max_appointments=None,
        source="fallback",
        booking_min_advance_hours=booking_min_advance_hours,
        booking_max_advance_days=booking_max_advance_days,
        cancel_min_hours=cancel_min_hours,
        max_reschedules_per_appointment=max_reschedules_per_appointment,
        max_active_per_requester_per_day=max_active_per_requester_per_day,
        waitlist_max_per_day=waitlist_max_per_day,
        default_slot_step_minutes=default_slot_step_minutes,
    )
