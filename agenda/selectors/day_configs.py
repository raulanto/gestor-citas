"""Selectors for day configuration resolution."""

import datetime

from agenda.models import DayConfig
from agenda.selectors.types import DayConfigResolved


def resolve_day_config(target_date: datetime.date) -> DayConfigResolved:
    """Resolve the effective day configuration for a given date.

    Priority:
    1. Single-date override (DayConfig.date == target_date)
    2. Weekday default (DayConfig.weekday == target_date.weekday())
    3. Fallback default (is_open=True, max_appointments=None, source="fallback")
    """
    # 1. Date override
    date_override = DayConfig.objects.filter(date=target_date).first()
    if date_override is not None:
        return DayConfigResolved(
            date=target_date,
            is_open=date_override.is_open,
            max_appointments=date_override.max_appointments,
            source="date_override",
        )

    # 2. Weekday default
    weekday_default = DayConfig.objects.filter(weekday=target_date.weekday()).first()
    if weekday_default is not None:
        return DayConfigResolved(
            date=target_date,
            is_open=weekday_default.is_open,
            max_appointments=weekday_default.max_appointments,
            source="weekday_default",
        )

    # 3. Fallback default
    return DayConfigResolved(
        date=target_date,
        is_open=True,
        max_appointments=None,
        source="fallback",
    )
