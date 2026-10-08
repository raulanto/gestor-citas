"""Tests for PII retention and requester anonymization."""

import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from agenda.constants import AppointmentStatus
from agenda.models import Appointment, Requester
from agenda.services.requesters import get_or_create_requester
from agenda.services.retention import anonymize_requesters
from agenda.tests.factories import AppointmentFactory, RequesterFactory, ServiceFactory


@pytest.fixture
def tz():
    return ZoneInfo("America/Mexico_City")


@pytest.mark.django_db
def test_requester_constraint_permits_anonymized_empty_contact():
    """CheckConstraint permits empty contact when anonymized_at is set, but rejects when null."""
    # 1. Non-anonymized without contact -> Validation error
    req_invalid = Requester(full_name="Test User", phone="", email="", anonymized_at=None)
    with pytest.raises(ValidationError):
        req_invalid.full_clean()

    # 2. Anonymized without contact -> Allowed
    req_valid = Requester(
        full_name="Solicitante anonimizado",
        phone="",
        email="",
        anonymized_at=timezone.now(),
    )
    req_valid.full_clean()
    req_valid.save()
    assert req_valid.id is not None


@pytest.mark.django_db
def test_anonymize_requesters_conditions(tz):
    """Only requesters with all terminal appointments older than cutoff get anonymized."""
    now = timezone.datetime(2026, 10, 15, 12, 0, tzinfo=tz)
    cutoff_date = now - datetime.timedelta(days=730)

    service = ServiceFactory(duration_minutes=30)

    # 1. Qualifying Requester A: old completed appointment
    req_a = RequesterFactory(
        full_name="Old User", phone="+52 993 111 2233", email="old@domain.com"
    )
    old_end = cutoff_date - datetime.timedelta(days=10)
    AppointmentFactory(
        requester=req_a,
        service=service,
        status=AppointmentStatus.COMPLETED,
        date=old_end.date(),
        start_at=old_end - datetime.timedelta(minutes=30),
        end_at=old_end,
    )

    # 2. Non-qualifying Requester B: has an ACTIVE appointment (CONFIRMED)
    req_b = RequesterFactory(
        full_name="Active User", phone="+52 993 222 3344", email="active@domain.com"
    )
    AppointmentFactory(
        requester=req_b,
        service=service,
        status=AppointmentStatus.COMPLETED,
        date=old_end.date(),
        start_at=old_end - datetime.timedelta(minutes=30),
        end_at=old_end,
    )
    AppointmentFactory(
        requester=req_b,
        service=service,
        status=AppointmentStatus.CONFIRMED,
        date=now.date(),
        start_at=now,
        end_at=now + datetime.timedelta(minutes=30),
    )

    # 3. Non-qualifying Requester C: has a RECENT terminal appointment
    req_c = RequesterFactory(
        full_name="Recent Cancel", phone="+52 993 333 4455", email="recent@domain.com"
    )
    recent_end = now - datetime.timedelta(days=30)
    AppointmentFactory(
        requester=req_c,
        service=service,
        status=AppointmentStatus.CANCELLED,
        date=recent_end.date(),
        start_at=recent_end - datetime.timedelta(minutes=30),
        end_at=recent_end,
    )

    # 4. Qualifying Requester D: no appointments, created before cutoff
    req_d = RequesterFactory(
        full_name="No Appts Old", phone="+52 993 444 5566", email="noappts@domain.com"
    )
    Requester.objects.filter(id=req_d.id).update(
        created_at=cutoff_date - datetime.timedelta(days=5)
    )

    # Test Dry Run
    dry_count = anonymize_requesters(older_than_days=730, now=now, dry_run=True)
    assert dry_count == 2
    # Verify nothing changed in DB during dry_run
    req_a.refresh_from_db()
    assert req_a.anonymized_at is None
    assert req_a.full_name == "Old User"

    # Test Real Execution
    count = anonymize_requesters(older_than_days=730, now=now, dry_run=False)
    assert count == 2

    req_a.refresh_from_db()
    assert req_a.anonymized_at == now
    assert req_a.full_name == "Solicitante anonimizado"
    assert req_a.phone == ""
    assert req_a.email == ""

    req_b.refresh_from_db()
    assert req_b.anonymized_at is None
    assert req_b.full_name == "Active User"

    req_c.refresh_from_db()
    assert req_c.anonymized_at is None
    assert req_c.full_name == "Recent Cancel"

    req_d.refresh_from_db()
    assert req_d.anonymized_at == now
    assert req_d.full_name == "Solicitante anonimizado"

    # Appointments and events are preserved
    assert Appointment.objects.count() == 4

    # Idempotent execution
    second_count = anonymize_requesters(older_than_days=730, now=now, dry_run=False)
    assert second_count == 0


@pytest.mark.django_db
def test_get_or_create_requester_does_not_reuse_anonymized():
    """get_or_create_requester never links new appointments to an anonymized requester record."""
    anonymized = RequesterFactory(
        full_name="Solicitante anonimizado",
        phone="",
        email="",
        anonymized_at=timezone.now(),
    )

    new_req = get_or_create_requester(
        full_name="Juan Perez",
        phone="+52 993 123 4567",
        email="juan@example.com",
    )
    assert new_req.id != anonymized.id
    assert new_req.anonymized_at is None


@pytest.mark.django_db
def test_anonymize_requesters_management_command(tz):
    """Management command anonymize_requesters accepts --older-than-days and --dry-run flags."""
    now = timezone.now()
    service = ServiceFactory(duration_minutes=30)
    req = RequesterFactory(full_name="Old To Anonymize", phone="+52 993 999 0000")
    old_date = (now - datetime.timedelta(days=100)).date()
    AppointmentFactory(
        requester=req,
        service=service,
        status=AppointmentStatus.COMPLETED,
        date=old_date,
        start_at=timezone.datetime.combine(old_date, datetime.time(9, 0), tzinfo=tz),
        end_at=timezone.datetime.combine(old_date, datetime.time(9, 30), tzinfo=tz),
    )

    out = StringIO()
    call_command("anonymize_requesters", "--older-than-days", "90", "--dry-run", stdout=out)
    output = out.getvalue()
    assert "dry-run" in output
    assert "1" in output

    req.refresh_from_db()
    assert req.anonymized_at is None

    out = StringIO()
    call_command("anonymize_requesters", "--older-than-days", "90", stdout=out)
    output = out.getvalue()
    assert "Solicitantes anonimizados: 1" in output

    req.refresh_from_db()
    assert req.anonymized_at is not None
