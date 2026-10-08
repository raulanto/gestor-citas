"""Tests for appointment state transitions and the transition guardian."""

import ast
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from agenda.constants import AppointmentStatus, EventNote
from agenda.exceptions import InvalidStateTransition
from agenda.models import AppointmentEvent
from agenda.services.transitions import reassign_worker, transition
from agenda.tests.factories import AppointmentFactory, WorkerFactory

User = get_user_model()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "from_status,to_status",
    [
        (AppointmentStatus.WAITLISTED, AppointmentStatus.CONFIRMED),
        (AppointmentStatus.WAITLISTED, AppointmentStatus.CANCELLED),
        (AppointmentStatus.WAITLISTED, AppointmentStatus.EXPIRED),
        (AppointmentStatus.WAITLISTED, AppointmentStatus.RESCHEDULED),
        (AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED),
        (AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED),
        (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED),
        (AppointmentStatus.CONFIRMED, AppointmentStatus.NO_SHOW),
    ],
)
def test_allowed_transitions_succeed_and_record_event(from_status, to_status):
    worker = WorkerFactory() if to_status == AppointmentStatus.CONFIRMED else None
    appointment = AppointmentFactory(
        status=from_status,
        worker=WorkerFactory() if from_status == AppointmentStatus.CONFIRMED else None,
    )
    user = User.objects.create_user(username=f"user_{from_status}_{to_status}")

    updated = transition(
        appointment,
        to_status,
        actor=user,
        note=f"Transición a {to_status}",
        worker=worker,
    )

    appointment.refresh_from_db()
    assert appointment.status == to_status
    assert updated.status == to_status
    if to_status == AppointmentStatus.CONFIRMED:
        assert appointment.worker == worker

    event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
    assert event.from_status == from_status
    assert event.to_status == to_status
    assert event.actor == user
    assert event.note == f"Transición a {to_status}"
    if worker:
        assert event.worker == worker


@pytest.mark.django_db
def test_confirmed_to_waitlisted_via_revalidation():
    appointment = AppointmentFactory(status=AppointmentStatus.CONFIRMED)
    user = User.objects.create_user(username="revalidation_user")

    # 1. Without via_revalidation -> InvalidStateTransition
    with pytest.raises(InvalidStateTransition):
        transition(
            appointment,
            AppointmentStatus.WAITLISTED,
            actor=user,
            worker=None,
            via_revalidation=False,
        )

    # 2. With via_revalidation=True -> Success
    updated = transition(
        appointment,
        AppointmentStatus.WAITLISTED,
        actor=user,
        note=EventNote.WAITLISTED_SCHEDULE_CHANGE,
        worker=None,
        via_revalidation=True,
    )

    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.WAITLISTED
    assert appointment.worker is None
    assert updated.status == AppointmentStatus.WAITLISTED

    event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
    assert event.from_status == AppointmentStatus.CONFIRMED
    assert event.to_status == AppointmentStatus.WAITLISTED
    assert event.note == EventNote.WAITLISTED_SCHEDULE_CHANGE


@pytest.mark.django_db
def test_reassign_worker_service():
    worker1 = WorkerFactory()
    worker2 = WorkerFactory()
    appointment = AppointmentFactory(status=AppointmentStatus.CONFIRMED, worker=worker1)
    user = User.objects.create_user(username="reassigner")

    updated = reassign_worker(
        appointment,
        worker2,
        actor=user,
        note=EventNote.REASSIGNED_SCHEDULE_CHANGE,
    )

    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.worker == worker2
    assert updated.worker == worker2

    event = AppointmentEvent.objects.filter(appointment=appointment).latest("created_at")
    assert event.from_status == AppointmentStatus.CONFIRMED
    assert event.to_status == AppointmentStatus.CONFIRMED
    assert event.worker == worker2
    assert event.actor == user
    assert event.note == EventNote.REASSIGNED_SCHEDULE_CHANGE


@pytest.mark.django_db
@pytest.mark.parametrize(
    "from_status,to_status",
    [
        # Terminal states cannot transition to anything
        (AppointmentStatus.CANCELLED, AppointmentStatus.CONFIRMED),
        (AppointmentStatus.CANCELLED, AppointmentStatus.WAITLISTED),
        (AppointmentStatus.EXPIRED, AppointmentStatus.CONFIRMED),
        (AppointmentStatus.EXPIRED, AppointmentStatus.CANCELLED),
        (AppointmentStatus.RESCHEDULED, AppointmentStatus.CONFIRMED),
        (AppointmentStatus.RESCHEDULED, AppointmentStatus.CANCELLED),
        (AppointmentStatus.COMPLETED, AppointmentStatus.CONFIRMED),
        (AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED),
        (AppointmentStatus.NO_SHOW, AppointmentStatus.CONFIRMED),
        (AppointmentStatus.NO_SHOW, AppointmentStatus.CANCELLED),
        # Non-terminal disallowed transitions
        (AppointmentStatus.CONFIRMED, AppointmentStatus.EXPIRED),
        (AppointmentStatus.CONFIRMED, AppointmentStatus.WAITLISTED),
        (AppointmentStatus.WAITLISTED, AppointmentStatus.COMPLETED),
        (AppointmentStatus.WAITLISTED, AppointmentStatus.NO_SHOW),
    ],
)
def test_disallowed_transitions_raise_invalid_state_transition(from_status, to_status):
    appointment = AppointmentFactory(status=from_status)
    initial_events_count = AppointmentEvent.objects.filter(appointment=appointment).count()

    with pytest.raises(InvalidStateTransition) as exc_info:
        transition(appointment, to_status, note="Intento inválido")

    assert exc_info.value.http_status == 409
    appointment.refresh_from_db()
    assert appointment.status == from_status
    assert AppointmentEvent.objects.filter(appointment=appointment).count() == initial_events_count


def test_transition_guardian_no_direct_status_or_worker_mutation():
    """Guardian test: verify no file outside transitions.py assigns .status = or .worker =."""
    root_dir = Path(__file__).resolve().parent.parent  # agenda/
    violations = []

    for py_file in root_dir.rglob("*.py"):
        rel_path = py_file.relative_to(root_dir).as_posix()

        # Exclude transitions.py, tests, migrations, and factories
        if (
            rel_path == "services/transitions.py"
            or rel_path.startswith("migrations/")
            or rel_path.startswith("tests/")
            or rel_path == "tests/factories.py"
        ):
            continue

        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Check for: x.status = ... or x.worker = ...
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in ("status", "worker"):
                        # Skip if it's a class field definition like worker = models.ForeignKey(...)
                        is_model_field = False
                        if isinstance(node.value, ast.Call) and isinstance(
                            node.value.func, ast.Attribute
                        ):
                            func_val = node.value.func.value
                            if isinstance(func_val, ast.Name) and func_val.id == "models":
                                is_model_field = True
                        if not is_model_field:
                            violations.append(
                                f"{rel_path}:{node.lineno} assigns directly to .{target.attr}"
                            )
            # Check for: x.update(..., status=...) or x.update(..., worker=...)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "update":
                    for keyword in node.keywords:
                        if keyword.arg in ("status", "worker"):
                            violations.append(
                                f"{rel_path}:{node.lineno} calls .update({keyword.arg}=...)"
                            )

    assert not violations, "Guardian violations found:\n" + "\n".join(violations)
