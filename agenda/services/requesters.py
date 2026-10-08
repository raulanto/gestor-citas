"""Service functions for requester normalization and resolution."""

import re

from django.core.exceptions import ValidationError

from agenda.models import Requester


def normalize_phone(raw: str | None) -> str:
    """Normalize phone number to digits only and strip Mexico country code '52' if 12 digits."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 12 and digits.startswith("52"):
        return digits[2:]
    return digits


def get_or_create_requester(
    *,
    full_name: str,
    phone: str | None = None,
    email: str | None = None,
) -> Requester:
    """Find an existing requester by phone or email, or create a new one.

    If an existing requester is found, returns the existing record without overwriting
    its full_name.
    """
    clean_name = (full_name or "").strip()
    clean_phone = normalize_phone(phone)
    clean_email = (email or "").strip().lower()

    if not clean_phone and not clean_email:
        raise ValidationError("Debe proporcionar al menos un teléfono o un correo electrónico.")

    if clean_phone:
        existing = Requester.objects.filter(phone=clean_phone, anonymized_at__isnull=True).first()
        if existing is not None:
            return existing

    if clean_email:
        existing = Requester.objects.filter(email=clean_email, anonymized_at__isnull=True).first()
        if existing is not None:
            return existing

    return Requester.objects.create(
        full_name=clean_name,
        phone=clean_phone,
        email=clean_email,
    )

