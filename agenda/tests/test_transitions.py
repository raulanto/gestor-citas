"""Tests for appointment state transitions and the transition guardian."""

import ast
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from agenda.constants import ALLOWED_TRANSITIONS, AppointmentStatus
from agenda.exceptions import InvalidStateTransition
from agenda.models import Appointment, AppointmentEvent
from agenda.services.transitions import transition
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
    assert (
        AppointmentEvent.objects.filter(appointment=appointment).count() == initial_events_count
    )


def test_transition_guardian_no_direct_status_mutation():
    """Guardian test: verify no file in agenda/ outside transitions.py assigns .status = or updates it."""
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
            # Check for: x.status = ...
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "status":
                        violations.append(f"{rel_path}:{node.lineno} assigns directly to .status")
            # Check for: x.update(..., status=...) or filter(...).update(status=...)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "update":
                    for keyword in node.keywords:
                        if keyword.arg == "status":
                            violations.append(
                                f"{rel_path}:{node.lineno} calls .update(status=...)"
                            )

    assert not violations, f"Guardian violations found:\n" + "\n".join(violations)
