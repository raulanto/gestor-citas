"""Appointment busy slots adapter implementing BusySlotsPort."""

import datetime
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from agenda.constants import OCCUPYING_STATUSES, QUOTA_STATUSES
from agenda.models import Appointment
from agenda.services.capacity import Interval


class AppointmentBusySlots:
    """Database adapter for querying occupied intervals and active quota counts."""

    def busy_intervals(self, target_date: datetime.date) -> dict[int, Sequence[Interval]]:
        """Return occupied intervals grouped by worker_id in local time."""
        tz = ZoneInfo(settings.TIME_ZONE)
        appointments = (
            Appointment.objects.filter(
                date=target_date,
                status__in=OCCUPYING_STATUSES,
                worker__isnull=False,
            )
            .values_list("worker_id", "start_at", "end_at")
            .order_by("start_at")
        )

        result: dict[int, list[Interval]] = {}
        for worker_id, start_at, end_at in appointments:
            local_start = timezone.localtime(start_at, tz).time()
            local_end = timezone.localtime(end_at, tz).time()
            result.setdefault(worker_id, []).append(Interval(local_start, local_end))

        return result

    def active_count(self, target_date: datetime.date) -> int:
        """Return count of appointments consuming daily quota for the given date."""
        return Appointment.objects.filter(
            date=target_date,
            status__in=QUOTA_STATUSES,
        ).count()
