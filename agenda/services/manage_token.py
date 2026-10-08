"""Service for generating, verifying, and rotating secure appointment management tokens."""

import hashlib
import hmac
import secrets
from typing import Any

from agenda.constants import EventNote
from agenda.models import Appointment, AppointmentEvent


def issue_manage_token(appointment: Appointment) -> str:
    """Generate a secure manage token, persist only its SHA-256 hash, and return the raw token."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    appointment.manage_token_hash = token_hash
    appointment.save(update_fields=["manage_token_hash", "updated_at"])
    return raw_token


def verify_manage_token(appointment: Appointment, raw: str | None) -> bool:
    """Verify in constant time whether raw token matches the stored SHA-256 hash."""
    if not raw or not appointment.manage_token_hash:
        return False

    raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hmac.compare_digest(raw_hash, appointment.manage_token_hash)


def rotate_manage_token(appointment: Appointment, *, actor: Any = None) -> str:
    """Rotate an appointment's management token, invalidating previous ones and logging an audit event."""
    new_raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(new_raw_token.encode("utf-8")).hexdigest()

    appointment.manage_token_hash = token_hash
    appointment.save(update_fields=["manage_token_hash", "updated_at"])

    AppointmentEvent.objects.create(
        appointment=appointment,
        from_status=appointment.status,
        to_status=appointment.status,
        worker=appointment.worker,
        actor=actor,
        note=EventNote.MANAGE_TOKEN_ROTATED,
    )
    return new_raw_token
