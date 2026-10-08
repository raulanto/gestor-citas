"""Worker schedule management, revalidation, and confirmation workflows."""

import datetime
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from agenda.constants import AppointmentStatus, EventNote
from agenda.exceptions import (
    ScheduleChangeNeedsConfirmation,
    WorkerNotFound,
)
from agenda.logging import log_event
from agenda.models import (
    Appointment,
    ScheduleException,
    Worker,
    WorkSchedule,
)
from agenda.selectors.schedules import get_day_config_summary
from agenda.selectors.workers import list_available_workers_on, resolve_worker_shift
from agenda.services.assignment import pick_worker
from agenda.services.capacity import Interval, work_segments
from agenda.services.locks import day_advisory_lock, day_advisory_locks
from agenda.services.transitions import reassign_worker, transition
from agenda.services.waitlist import process_waitlist


@dataclass(frozen=True)
class DisplacedAppointmentInfo:
    """Detailed record of an appointment displaced by a worker schedule change."""

    appointment_id: uuid.UUID
    date: datetime.date
    start_at: datetime.datetime
    requester_name: str
    outcome: str  # "REASSIGNED" or "WAITLISTED"
    new_worker_name: str | None
    unserviceable: bool

    def to_dict(self) -> dict:
        return {
            "appointment_id": str(self.appointment_id),
            "date": self.date.isoformat(),
            "start_at": self.start_at.isoformat(),
            "requester_name": self.requester_name,
            "outcome": self.outcome,
            "new_worker_name": self.new_worker_name,
            "unserviceable": self.unserviceable,
        }


@dataclass(frozen=True)
class RevalidationResult:
    """Summary of revalidation effects across all evaluated dates."""

    displaced: list[DisplacedAppointmentInfo]
    reassigned: int
    waitlisted: int
    unserviceable: int
    promoted_from_waitlist: int
    over_quota: list[str]

    def to_dict(self) -> dict:
        return {
            "displaced": [d.to_dict() for d in self.displaced],
            "reassigned": self.reassigned,
            "waitlisted": self.waitlisted,
            "unserviceable": self.unserviceable,
            "promoted_from_waitlist": self.promoted_from_waitlist,
            "over_quota": self.over_quota,
        }


@dataclass(frozen=True)
class ScheduleChangeResult:
    """Result of applying or dry-running a schedule modification."""

    applied: bool
    impact: dict


def revalidate_worker(
    worker_id: int,
    *,
    actor: AbstractBaseUser | None = None,
    now: datetime.datetime | None = None,
    dates: list[datetime.date] | None = None,
) -> RevalidationResult:
    """Revalidate future confirmed appointments for a worker after schedule or status changes.

    Displaced appointments are first attempted to be reassigned to another available worker;
    if none are free, they transition to WAITLISTED preserving their creation timestamp.
    Triggers waitlist processing at the end of each processed date.
    """
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)

    worker = Worker.objects.filter(id=worker_id).first()
    if worker is None:
        raise WorkerNotFound()

    if dates is not None:
        target_dates = sorted(set(dates))
    else:
        query = Appointment.objects.filter(
            worker_id=worker_id,
            status=AppointmentStatus.CONFIRMED,
            start_at__gt=now_local,
        )
        target_dates = sorted(set(query.values_list("date", flat=True)))

    displaced_list: list[DisplacedAppointmentInfo] = []
    reassigned_count = 0
    waitlisted_count = 0
    unserviceable_count = 0
    promoted_count = 0
    over_quota_dates: list[str] = []

    for target_date in target_dates:
        with transaction.atomic(), day_advisory_lock(target_date):
            # Compute effective shift and work segments for the affected worker
            if not worker.is_active:
                worker_segments: list[Interval] = []
            else:
                shift = resolve_worker_shift(worker, target_date)
                worker_segments = work_segments(shift) if shift is not None else []

            # Fetch confirmed appointments under lock
            confirmed_appts = list(
                Appointment.objects.filter(
                    worker_id=worker_id,
                    date=target_date,
                    status=AppointmentStatus.CONFIRMED,
                    start_at__gt=now_local,
                )
                .select_related("requester", "service")
                .order_by("created_at", "id")
                .select_for_update()
            )

            # Determine displaced appointments
            displaced_for_date: list[Appointment] = []
            for appt in confirmed_appts:
                slot_start = timezone.localtime(appt.start_at, tz).time()
                slot_end = timezone.localtime(appt.end_at, tz).time()
                slot_interval = Interval(slot_start, slot_end)
                if not any(slot_interval.is_subset_of(seg) for seg in worker_segments):
                    displaced_for_date.append(appt)

            if displaced_for_date:
                # Load other available workers on this date
                all_available = list_available_workers_on(target_date)
                other_workers = [(w, s) for w, s in all_available if w.id != worker_id]

                # Map occupying appointments for other workers
                busy_map: dict[int, list[Interval]] = {w.id: [] for w, _ in other_workers}
                daily_loads: dict[int, int] = {w.id: 0 for w, _ in other_workers}

                other_ids = [w.id for w, _ in other_workers]
                if other_ids:
                    occupying = Appointment.objects.filter(
                        date=target_date,
                        worker_id__in=other_ids,
                        status__in=[
                            AppointmentStatus.CONFIRMED,
                            AppointmentStatus.COMPLETED,
                            AppointmentStatus.NO_SHOW,
                        ],
                    )
                    for occ in occupying:
                        occ_start = timezone.localtime(occ.start_at, tz).time()
                        occ_end = timezone.localtime(occ.end_at, tz).time()
                        busy_map[occ.worker_id].append(Interval(occ_start, occ_end))
                        daily_loads[occ.worker_id] += 1

                # Reassign or waitlist displaced appointments in FIFO order
                for appt in displaced_for_date:
                    slot_start = timezone.localtime(appt.start_at, tz).time()
                    slot_end = timezone.localtime(appt.end_at, tz).time()
                    slot_interval = Interval(slot_start, slot_end)

                    candidates: list[Worker] = []
                    for w, s in other_workers:
                        segments = work_segments(s)
                        if any(slot_interval.is_subset_of(seg) for seg in segments):
                            candidates.append(w)

                    assigned = (
                        pick_worker(
                            candidates=candidates,
                            slot_interval=slot_interval,
                            busy_map=busy_map,
                            daily_loads=daily_loads,
                        )
                        if candidates
                        else None
                    )

                    if assigned is not None:
                        reassign_worker(
                            appt,
                            assigned,
                            actor=actor,
                            note=EventNote.REASSIGNED_SCHEDULE_CHANGE,
                        )
                        busy_map[assigned.id].append(slot_interval)
                        daily_loads[assigned.id] += 1
                        displaced_list.append(
                            DisplacedAppointmentInfo(
                                appointment_id=appt.id,
                                date=target_date,
                                start_at=appt.start_at,
                                requester_name=appt.requester.full_name,
                                outcome="REASSIGNED",
                                new_worker_name=assigned.full_name,
                                unserviceable=False,
                            )
                        )
                        reassigned_count += 1
                    else:
                        transition(
                            appt,
                            AppointmentStatus.WAITLISTED,
                            actor=actor,
                            note=EventNote.WAITLISTED_SCHEDULE_CHANGE,
                            worker=None,
                            via_revalidation=True,
                        )
                        # Check if unserviceable across all currently active workers
                        is_unserv = not any(
                            any(slot_interval.is_subset_of(seg) for seg in work_segments(s))
                            for _, s in all_available
                        )
                        if is_unserv:
                            unserviceable_count += 1

                        displaced_list.append(
                            DisplacedAppointmentInfo(
                                appointment_id=appt.id,
                                date=target_date,
                                start_at=appt.start_at,
                                requester_name=appt.requester.full_name,
                                outcome="WAITLISTED",
                                new_worker_name=None,
                                unserviceable=is_unserv,
                            )
                        )
                        waitlisted_count += 1

            # Trigger waitlist promotion for this date in case shifts expanded or slots freed
            wl_result = process_waitlist(target_date, now=now)
            promoted_count += len(wl_result.assigned)

            # Check for over-quota state
            summary = get_day_config_summary(target_date)
            if summary.is_over_quota:
                over_quota_dates.append(target_date.isoformat())

    result = RevalidationResult(
        displaced=displaced_list,
        reassigned=reassigned_count,
        waitlisted=waitlisted_count,
        unserviceable=unserviceable_count,
        promoted_from_waitlist=promoted_count,
        over_quota=over_quota_dates,
    )
    log_event(
        "schedule_changed",
        worker_id=worker_id,
        reassigned=result.reassigned,
        waitlisted=result.waitlisted,
        unserviceable=result.unserviceable,
    )
    return result


def revalidate_all(
    now: datetime.datetime | None = None,
    from_date: datetime.date | None = None,
) -> list[RevalidationResult]:
    """Safety sweep: revalidates future confirmed appointments across all workers."""
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)
    today = from_date if from_date is not None else now_local.date()

    worker_ids = sorted(
        set(
            Appointment.objects.filter(
                status=AppointmentStatus.CONFIRMED,
                start_at__gt=now_local,
                date__gte=today,
                worker__isnull=False,
            ).values_list("worker_id", flat=True)
        )
    )

    results: list[RevalidationResult] = []
    for w_id in worker_ids:
        results.append(revalidate_worker(w_id, now=now))

    return results


def _collect_worker_future_dates(
    worker: Worker,
    now: datetime.datetime | None = None,
) -> list[datetime.date]:
    """Collect all future dates where the worker currently has confirmed appointments."""
    tz = ZoneInfo(settings.TIME_ZONE)
    if now is None:
        now = timezone.now()
    now_local = timezone.localtime(now, tz)

    return sorted(
        set(
            Appointment.objects.filter(
                worker=worker,
                status=AppointmentStatus.CONFIRMED,
                start_at__gt=now_local,
            ).values_list("date", flat=True)
        )
    )


def set_weekly_schedule(
    worker: Worker,
    entries: list[dict],
    *,
    actor: AbstractBaseUser | None = None,
    confirm: bool = False,
    dry_run: bool = False,
    now: datetime.datetime | None = None,
) -> ScheduleChangeResult:
    """Replace a worker's complete weekly work schedule with atomic validation and confirmation."""
    # Pre-validate entries
    temp_schedules: list[WorkSchedule] = []
    for entry in entries:
        sched = WorkSchedule(
            worker=worker,
            weekday=entry["weekday"],
            start_time=entry["start_time"],
            end_time=entry["end_time"],
            break_start=entry.get("break_start"),
            break_end=entry.get("break_end"),
        )
        sched.clean()
        temp_schedules.append(sched)

    future_dates = _collect_worker_future_dates(worker, now=now)

    with transaction.atomic(), day_advisory_locks(*future_dates):
        sid = transaction.savepoint_create()

        WorkSchedule.objects.filter(worker=worker).delete()
        for sched in temp_schedules:
            sched.save()

        reval = revalidate_worker(worker.id, actor=actor, now=now, dates=future_dates)
        impact = reval.to_dict()

        if reval.displaced and not confirm:
            transaction.savepoint_rollback(sid)
            if dry_run:
                return ScheduleChangeResult(applied=False, impact=impact)
            raise ScheduleChangeNeedsConfirmation(impact=impact)

        if dry_run:
            transaction.savepoint_rollback(sid)
            return ScheduleChangeResult(applied=False, impact=impact)

        transaction.savepoint_commit(sid)
        return ScheduleChangeResult(applied=True, impact=impact)


def add_exception(
    worker: Worker,
    data: dict,
    *,
    actor: AbstractBaseUser | None = None,
    confirm: bool = False,
    dry_run: bool = False,
    now: datetime.datetime | None = None,
) -> ScheduleChangeResult:
    """Add a schedule exception for a worker with impact evaluation and confirmation."""
    exc = ScheduleException(
        worker=worker,
        date=data["date"],
        kind=data["kind"],
        start_time=data.get("start_time"),
        end_time=data.get("end_time"),
        break_start=data.get("break_start"),
        break_end=data.get("break_end"),
        reason=data.get("reason", ""),
    )
    exc.clean()

    target_date = data["date"]
    affected_dates = sorted(set(_collect_worker_future_dates(worker, now=now) + [target_date]))

    with transaction.atomic(), day_advisory_locks(*affected_dates):
        sid = transaction.savepoint_create()
        exc.save()

        reval = revalidate_worker(worker.id, actor=actor, now=now, dates=[target_date])
        impact = reval.to_dict()

        if reval.displaced and not confirm:
            transaction.savepoint_rollback(sid)
            if dry_run:
                return ScheduleChangeResult(applied=False, impact=impact)
            raise ScheduleChangeNeedsConfirmation(impact=impact)

        if dry_run:
            transaction.savepoint_rollback(sid)
            return ScheduleChangeResult(applied=False, impact=impact)

        transaction.savepoint_commit(sid)
        return ScheduleChangeResult(applied=True, impact=impact)


def remove_exception(
    exception: ScheduleException,
    *,
    actor: AbstractBaseUser | None = None,
    confirm: bool = False,
    dry_run: bool = False,
    now: datetime.datetime | None = None,
) -> ScheduleChangeResult:
    """Remove a schedule exception and revalidate affected appointments."""
    worker = exception.worker
    target_date = exception.date
    affected_dates = sorted(set(_collect_worker_future_dates(worker, now=now) + [target_date]))

    with transaction.atomic(), day_advisory_locks(*affected_dates):
        sid = transaction.savepoint_create()
        exception.delete()

        reval = revalidate_worker(worker.id, actor=actor, now=now, dates=[target_date])
        impact = reval.to_dict()

        if reval.displaced and not confirm:
            transaction.savepoint_rollback(sid)
            if dry_run:
                return ScheduleChangeResult(applied=False, impact=impact)
            raise ScheduleChangeNeedsConfirmation(impact=impact)

        if dry_run:
            transaction.savepoint_rollback(sid)
            return ScheduleChangeResult(applied=False, impact=impact)

        transaction.savepoint_commit(sid)
        return ScheduleChangeResult(applied=True, impact=impact)


def set_worker_active(
    worker: Worker,
    is_active: bool,
    *,
    actor: AbstractBaseUser | None = None,
    confirm: bool = False,
    dry_run: bool = False,
    now: datetime.datetime | None = None,
) -> ScheduleChangeResult:
    """Activate or deactivate a worker with revalidation of future appointments."""
    future_dates = _collect_worker_future_dates(worker, now=now)

    with transaction.atomic(), day_advisory_locks(*future_dates):
        sid = transaction.savepoint_create()
        worker.is_active = is_active
        worker.save(update_fields=["is_active", "updated_at"])

        reval = revalidate_worker(worker.id, actor=actor, now=now, dates=future_dates)
        impact = reval.to_dict()

        if reval.displaced and not confirm:
            transaction.savepoint_rollback(sid)
            if dry_run:
                return ScheduleChangeResult(applied=False, impact=impact)
            raise ScheduleChangeNeedsConfirmation(impact=impact)

        if dry_run:
            transaction.savepoint_rollback(sid)
            return ScheduleChangeResult(applied=False, impact=impact)

        transaction.savepoint_commit(sid)
        return ScheduleChangeResult(applied=True, impact=impact)
