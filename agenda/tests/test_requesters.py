"""Unit tests for requester normalization and resolution service."""

import pytest
from django.core.exceptions import ValidationError

from agenda.models import Requester
from agenda.services.requesters import get_or_create_requester, normalize_phone


def test_normalize_phone():
    assert normalize_phone("+52 993 123 4567") == "9931234567"
    assert normalize_phone("9931234567") == "9931234567"
    assert normalize_phone("993-123-4567") == "9931234567"
    assert normalize_phone("+52 (993) 123-4567") == "9931234567"
    assert normalize_phone(None) == ""
    assert normalize_phone("") == ""
    assert normalize_phone("5512345678") == "5512345678"


@pytest.mark.django_db
def test_get_or_create_requester_resolves_same_phone_variants():
    req1 = get_or_create_requester(
        full_name="Ana Pérez",
        phone="+52 993 123 4567",
        email="ana@example.com",
    )
    req2 = get_or_create_requester(
        full_name="Ana P. (Distinto Nombre)",
        phone="993-123-4567",
        email="otra@example.com",
    )

    assert req1.id == req2.id
    req1.refresh_from_db()
    # Name should NOT be overwritten
    assert req1.full_name == "Ana Pérez"
    assert Requester.objects.count() == 1


@pytest.mark.django_db
def test_get_or_create_requester_resolves_case_insensitive_email():
    req1 = get_or_create_requester(
        full_name="Carlos Ruiz",
        phone="",
        email="Carlos.Ruiz@Example.COM",
    )
    req2 = get_or_create_requester(
        full_name="Carlos R.",
        phone="",
        email="carlos.ruiz@example.com",
    )

    assert req1.id == req2.id
    assert Requester.objects.count() == 1


@pytest.mark.django_db
def test_get_or_create_requester_creates_new_record():
    req = get_or_create_requester(
        full_name="Elena Morales",
        phone="5551234567",
        email="elena@example.com",
    )

    assert req.id is not None
    assert req.full_name == "Elena Morales"
    assert req.phone == "5551234567"
    assert req.email == "elena@example.com"
    assert Requester.objects.count() == 1


@pytest.mark.django_db
def test_get_or_create_requester_without_phone_or_email_raises_validation_error():
    with pytest.raises(ValidationError):
        get_or_create_requester(
            full_name="Sin Contacto",
            phone="",
            email="",
        )
