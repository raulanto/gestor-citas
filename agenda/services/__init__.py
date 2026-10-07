"""Agenda services package for domain business logic."""

from agenda.services.assignment import pick_worker
from agenda.services.booking import (
    BookingResult,
    book_appointment,
    create_appointment_in_lock,
)
from agenda.services.cancellation import (
    cancel_appointment,
    cancel_appointments_for_day,
    reschedule_appointment,
)
from agenda.services.capacity import (
    Interval,
    Shift,
    effective_quota,
    generate_slots,
    personnel_capacity,
    work_segments,
    worker_capacity,
)
from agenda.services.completion import complete_appointment, mark_no_show
from agenda.services.locks import (
    acquire_day_advisory_lock,
    day_advisory_lock,
    day_advisory_locks,
)
from agenda.services.requesters import get_or_create_requester, normalize_phone
from agenda.services.transitions import transition
from agenda.services.waitlist import (
    WaitlistResult,
    expire_waitlist,
    process_waitlist,
    process_waitlist_all,
    schedule_waitlist_processing,
)

__all__ = [
    "BookingResult",
    "Interval",
    "Shift",
    "WaitlistResult",
    "acquire_day_advisory_lock",
    "book_appointment",
    "cancel_appointment",
    "cancel_appointments_for_day",
    "complete_appointment",
    "create_appointment_in_lock",
    "day_advisory_lock",
    "day_advisory_locks",
    "effective_quota",
    "expire_waitlist",
    "generate_slots",
    "get_or_create_requester",
    "mark_no_show",
    "normalize_phone",
    "personnel_capacity",
    "pick_worker",
    "process_waitlist",
    "process_waitlist_all",
    "reschedule_appointment",
    "schedule_waitlist_processing",
    "transition",
    "work_segments",
    "worker_capacity",
]

