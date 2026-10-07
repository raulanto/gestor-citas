"""Database locking utilities for agenda concurrency control."""

import datetime
import threading
from contextlib import contextmanager

from django.db import connection

# Advisory lock namespace identifier for appointment bookings and waitlist processing
APPOINTMENT_BOOKING_LOCK_NAMESPACE = 42

_sqlite_locks: dict[datetime.date, threading.Lock] = {}
_sqlite_global_lock = threading.Lock()


def _get_sqlite_lock(target_date: datetime.date) -> threading.Lock:
    with _sqlite_global_lock:
        if target_date not in _sqlite_locks:
            _sqlite_locks[target_date] = threading.Lock()
        return _sqlite_locks[target_date]


def acquire_day_advisory_lock(target_date: datetime.date) -> None:
    """Acquire a PostgreSQL transaction-level advisory lock for the given date.

    Serializes booking and waitlist operations for the same date without requiring
    a pre-existing DayConfig row. Automatically released at the end of the surrounding transaction.
    No-op on non-PostgreSQL database backends (e.g., SQLite).
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s);",
                [APPOINTMENT_BOOKING_LOCK_NAMESPACE, target_date.toordinal()],
            )


@contextmanager
def day_advisory_lock(target_date: datetime.date):
    """Context manager acquiring date advisory lock and cross-thread serialization."""
    acquire_day_advisory_lock(target_date)
    if connection.vendor == "sqlite":
        lock = _get_sqlite_lock(target_date)
        with lock:
            yield
    else:
        yield


@contextmanager
def day_advisory_locks(*target_dates: datetime.date):
    """Context manager acquiring advisory locks for multiple dates in ascending order.

    Locks dates in strict ascending order to prevent deadlocks when operations touch multiple days.
    """
    sorted_unique_dates = sorted(set(target_dates))
    for d in sorted_unique_dates:
        acquire_day_advisory_lock(d)

    if connection.vendor == "sqlite":
        locks = [_get_sqlite_lock(d) for d in sorted_unique_dates]
        # Acquire all SQLite thread locks in ascending order
        from contextlib import ExitStack

        with ExitStack() as stack:
            for lk in locks:
                stack.enter_context(lk)
            yield
    else:
        yield

