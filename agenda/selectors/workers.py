"""Selectors for worker shift resolution and availability queries."""

import datetime

from django.db.models import Prefetch

from agenda.models import ExceptionKind, ScheduleException, Worker, WorkSchedule
from agenda.selectors.types import Shift


def resolve_worker_shift(worker: Worker, target_date: datetime.date) -> Shift | None:
    """Resolve the effective working shift for a worker on a specific date.

    Priority:
    1. If worker is inactive -> None
    2. Single-date exception (ScheduleException.date == target_date):
       - ABSENCE -> None
       - SPECIAL_HOURS -> Shift from exception hours
    3. Weekly regular schedule (WorkSchedule.weekday == target_date.weekday()) -> Shift
    4. Otherwise -> None (worker does not work on this day)
    """
    if not worker.is_active:
        return None

    # Check prefetched exceptions if available to avoid extra DB queries
    if hasattr(worker, "prefetched_exceptions"):
        exceptions = [exc for exc in worker.prefetched_exceptions if exc.date == target_date]
        exception = exceptions[0] if exceptions else None
    else:
        exception = worker.schedule_exceptions.filter(date=target_date).first()

    if exception is not None:
        if exception.kind == ExceptionKind.ABSENCE:
            return None
        elif exception.kind == ExceptionKind.SPECIAL_HOURS:
            return Shift(
                start=exception.start_time,
                end=exception.end_time,
                break_start=exception.break_start,
                break_end=exception.break_end,
            )

    # Check prefetched schedules if available
    target_weekday = target_date.weekday()
    if hasattr(worker, "prefetched_schedules"):
        schedules = [s for s in worker.prefetched_schedules if s.weekday == target_weekday]
        schedule = schedules[0] if schedules else None
    else:
        schedule = worker.schedules.filter(weekday=target_weekday).first()

    if schedule is not None:
        return Shift(
            start=schedule.start_time,
            end=schedule.end_time,
            break_start=schedule.break_start,
            break_end=schedule.break_end,
        )

    return None


def list_available_workers_on(target_date: datetime.date) -> list[tuple[Worker, Shift]]:
    """List all active workers with their effective shift on a target date.

    Optimized to prevent N+1 queries by prefetching relevant exceptions and schedules.
    """
    target_weekday = target_date.weekday()

    workers = (
        Worker.objects.filter(is_active=True)
        .prefetch_related(
            Prefetch(
                "schedule_exceptions",
                queryset=ScheduleException.objects.filter(date=target_date),
                to_attr="prefetched_exceptions",
            ),
            Prefetch(
                "schedules",
                queryset=WorkSchedule.objects.filter(weekday=target_weekday),
                to_attr="prefetched_schedules",
            ),
        )
        .order_by("id")
    )

    available_workers: list[tuple[Worker, Shift]] = []
    for worker in workers:
        shift = resolve_worker_shift(worker, target_date)
        if shift is not None:
            available_workers.append((worker, shift))

    return available_workers
