"""Celery background tasks for agenda application."""

import datetime

from celery import shared_task

from agenda.services.schedules import revalidate_all
from agenda.services.waitlist import (
    expire_waitlist,
    process_waitlist,
    process_waitlist_all,
)


@shared_task(name="agenda.tasks.process_waitlist_task")
def process_waitlist_task(date_iso: str) -> dict:
    """Process waitlisted appointments for a specific date (ISO format YYYY-MM-DD)."""
    target_date = datetime.date.fromisoformat(date_iso)
    result = process_waitlist(target_date)
    return {
        "date": date_iso,
        "assigned_count": len(result.assigned),
        "remaining_count": result.remaining,
    }


@shared_task(name="agenda.tasks.process_waitlist_all_task")
def process_waitlist_all_task() -> dict:
    """Process waitlisted appointments for all active upcoming dates."""
    results = process_waitlist_all()
    total_assigned = sum(len(r.assigned) for r in results)
    return {
        "processed_dates_count": len(results),
        "total_assigned": total_assigned,
    }


@shared_task(name="agenda.tasks.waitlist_maintenance_task")
def waitlist_maintenance_task() -> dict:
    """Periodic maintenance: expire waitlist, revalidate shifts, promote waitlist."""
    expired_count = expire_waitlist()
    revalidation_results = revalidate_all()
    results = process_waitlist_all()
    total_assigned = sum(len(r.assigned) for r in results)
    total_displaced = sum(len(r.displaced) for r in revalidation_results)
    return {
        "expired_count": expired_count,
        "revalidated_workers_count": len(revalidation_results),
        "total_displaced": total_displaced,
        "processed_dates_count": len(results),
        "total_assigned": total_assigned,
    }
