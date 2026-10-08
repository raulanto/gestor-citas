"""Service for requester data retention and PII anonymization."""

import datetime

from django.db.models import Q
from django.utils import timezone

from agenda.constants import ACTIVE_STATUSES
from agenda.logging import log_event
from agenda.models import Appointment, Requester


def anonymize_requesters(
    older_than_days: int = 730,
    *,
    now: datetime.datetime | None = None,
    dry_run: bool = False,
) -> int:
    """Anonymize personal identification data for old and inactive requesters.

    Criteria for anonymization:
    - Requester is not already anonymized (`anonymized_at IS NULL`).
    - AND either:
        1. Has appointments, and ALL appointments are in terminal status
           (not in ACTIVE_STATUSES) with `end_at < threshold`.
        2. Has no appointments and was created before `threshold`.

    When anonymized:
    - `full_name` is set to "Solicitante anonimizado"
    - `phone` is set to ""
    - `email` is set to ""
    - `anonymized_at` is set to `now`

    Appointments, events, and metrics are preserved intact.

    Returns the number of requesters anonymized (or that would be anonymized if dry_run).
    """
    current_time = now or timezone.now()
    threshold = current_time - datetime.timedelta(days=older_than_days)

    # Requesters with active appointments cannot be anonymized
    active_requester_ids = Appointment.objects.filter(status__in=ACTIVE_STATUSES).values_list(
        "requester_id", flat=True
    )

    # Requesters with recent appointments (end_at >= threshold) cannot be anonymized
    recent_requester_ids = Appointment.objects.filter(end_at__gte=threshold).values_list(
        "requester_id", flat=True
    )

    # Candidate query
    candidates = (
        Requester.objects.filter(anonymized_at__isnull=True)
        .exclude(id__in=active_requester_ids)
        .exclude(id__in=recent_requester_ids)
        .filter(Q(appointments__isnull=False) | Q(created_at__lt=threshold))
        .distinct()
    )

    eligible_ids = list(candidates.values_list("id", flat=True))
    count = len(eligible_ids)

    if not dry_run and count > 0:
        Requester.objects.filter(id__in=eligible_ids).update(
            full_name="Solicitante anonimizado",
            phone="",
            email="",
            anonymized_at=current_time,
        )

    log_event("requesters_anonymized", count=count, dry_run=dry_run)
    return count
