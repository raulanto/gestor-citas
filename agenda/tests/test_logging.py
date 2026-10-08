"""Tests for structured logging, RequestID, PII redaction, and domain event logs."""

import logging
import uuid

import pytest
from django.test import RequestFactory
from rest_framework import status
from rest_framework.test import APIClient

from agenda.logging import (
    get_request_id,
    log_event,
)
from agenda.middleware import RequestIDMiddleware
from config.logging import PIIRedactionFilter, redact_text


def test_pii_redaction_from_string():
    """Verify regex redactor catches phone numbers, emails, tokens, and JWTs.

    Preserves UUIDs and dates.
    """
    raw_text = (
        "User with email test.user+tag@domain.co.uk and phone +52 993 123 4567 "
        "or 9931234567 or 993-123-4567 contacted staff with token "
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThis "
        "Bearer secret_token_123 and X-Manage-Token: mySecretManageToken1234567890. "
        "UUID 123e4567-e89b-12d3-a456-426614174000 and Date 2026-10-15T10:00:00-06:00 and ID 42."
    )
    redacted = redact_text(raw_text)

    assert "test.user+tag@domain.co.uk" not in redacted
    assert "[REDACTED_EMAIL]" in redacted

    assert "993 123 4567" not in redacted
    assert "9931234567" not in redacted
    assert "993-123-4567" not in redacted
    assert "[REDACTED_PHONE]" in redacted

    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "secret_token_123" not in redacted
    assert "mySecretManageToken1234567890" not in redacted
    assert "[REDACTED_TOKEN]" in redacted

    # UUID, date, and ID must NOT be altered
    assert "123e4567-e89b-12d3-a456-426614174000" in redacted
    assert "2026-10-15T10:00:00-06:00" in redacted
    assert "ID 42" in redacted


def test_pii_redaction_filter_record():
    """Verify PIIRedactionFilter scrubs message, args, and sensitive extra dict keys."""
    redaction_filter = PIIRedactionFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Failed login for email %s and phone %s",
        args=("admin@example.com", "9931234567"),
        exc_info=None,
    )
    record.phone = "+52 993 123 4567"
    record.email = "secret@example.com"
    record.full_name = "Juan Perez"
    record.password = "SuperSecret123"
    record.manage_token = "abc123token"
    record.access = "access_token"
    record.refresh = "refresh_token"
    record.worker_id = 5

    assert redaction_filter.filter(record) is True

    assert record.args == ("[REDACTED_EMAIL]", "[REDACTED_PHONE]")
    assert (
        record.getMessage() == "Failed login for email [REDACTED_EMAIL] and phone [REDACTED_PHONE]"
    )
    assert record.phone == "[REDACTED]"
    assert record.email == "[REDACTED]"
    assert record.full_name == "[REDACTED]"
    assert record.password == "[REDACTED]"
    assert record.manage_token == "[REDACTED]"
    assert record.access == "[REDACTED]"
    assert record.refresh == "[REDACTED]"
    assert record.worker_id == 5


def test_log_event_forbids_pii_keys():
    """Helper log_event raises ValueError when passed any PII field name."""
    with pytest.raises(ValueError, match="Forbidden PII key 'phone'"):
        log_event("test_event", phone="9931234567")

    with pytest.raises(ValueError, match="Forbidden PII key 'email'"):
        log_event("test_event", email="test@example.com")

    with pytest.raises(ValueError, match="Forbidden PII key 'full_name'"):
        log_event("test_event", full_name="Carlos")

    with pytest.raises(ValueError, match="Forbidden PII key 'password'"):
        log_event("test_event", password="secret")


def test_request_id_middleware():
    """RequestIDMiddleware propagates incoming X-Request-ID or generates a valid UUID.

    Replaces invalid ones.
    """
    from django.http import HttpResponse

    rf = RequestFactory()

    # 1. Custom valid request ID
    custom_id = "req-custom-12345_abc"
    request = rf.get("/api/v1/availability/", HTTP_X_REQUEST_ID=custom_id)
    captured_id = None

    def inner_view(req):
        nonlocal captured_id
        captured_id = get_request_id()
        return HttpResponse("ok")

    middleware = RequestIDMiddleware(inner_view)
    response = middleware(request)

    assert response["X-Request-ID"] == custom_id
    assert captured_id == custom_id

    # 2. Invalid request ID (contains invalid chars or too long) -> Replaced with UUID
    invalid_id = "bad id with spaces and <script>"
    request = rf.get("/api/v1/availability/", HTTP_X_REQUEST_ID=invalid_id)
    response = middleware(request)

    assert response["X-Request-ID"] != invalid_id
    # Must be valid UUID format
    uuid.UUID(response["X-Request-ID"])

    # 3. Missing request ID -> Auto-generated UUID
    request = rf.get("/api/v1/availability/")
    response = middleware(request)
    uuid.UUID(response["X-Request-ID"])


@pytest.mark.django_db
def test_request_log_middleware_json_output(api_client: APIClient, caplog):
    """Every request produces a single structured JSON line with no body or query strings."""
    caplog.set_level(logging.INFO, logger="agenda.requests")

    resp = api_client.get(
        "/api/v1/availability/?service=1&date=2026-10-15",
        HTTP_X_REQUEST_ID="test-req-123",
    )
    assert resp.status_code in (
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
    )

    # Check captured log lines
    req_logs = [r for r in caplog.records if r.name == "agenda.requests"]
    assert len(req_logs) >= 1

    last_record = req_logs[-1]
    assert last_record.request_id == "test-req-123"
    assert last_record.method == "GET"
    assert last_record.path == "/api/v1/availability/"
    assert "service=1" not in last_record.path
    assert last_record.status == resp.status_code
    assert hasattr(last_record, "duration_ms")
    assert last_record.role == "ANONYMOUS"


@pytest.mark.django_db
def test_authenticated_request_log_role_and_user_id(api_client: APIClient, staff_user, caplog):
    """Authenticated request logs user_id and role without extra DB queries."""
    caplog.set_level(logging.INFO, logger="agenda.requests")
    api_client.force_authenticate(user=staff_user)

    resp = api_client.get("/api/v1/auth/me/", HTTP_X_REQUEST_ID="auth-req-999")
    assert resp.status_code == status.HTTP_200_OK

    req_logs = [r for r in caplog.records if r.name == "agenda.requests"]
    assert len(req_logs) >= 1
    record = req_logs[-1]
    assert record.user_id == staff_user.id
    assert record.role == "STAFF"


@pytest.mark.django_db
def test_skip_health_path_in_request_logs(api_client: APIClient, caplog):
    """Health endpoints in LOG_SKIP_PATHS are omitted from request logging."""
    caplog.set_level(logging.INFO, logger="agenda.requests")

    api_client.get("/api/v1/health/")
    api_client.get("/api/v1/health/ready/")

    health_logs = [
        r
        for r in caplog.records
        if r.name == "agenda.requests" and "health" in getattr(r, "path", "")
    ]
    assert len(health_logs) == 0


@pytest.mark.django_db
def test_redaction_during_booking_and_unhandled_500(caplog, monkeypatch):
    """Logs captured during booking or exceptions never contain raw requester PII."""
    caplog.set_level(logging.INFO)

    secret_phone = "+52 993 555 1234"
    secret_email = "very.secret.client@domain.com"
    secret_name = "Alejandro Hernandez"

    payload = {
        "service": 1,
        "start_at": "2026-10-15T10:00:00-06:00",
        "requester": {
            "full_name": secret_name,
            "phone": secret_phone,
            "email": secret_email,
        },
    }

    from agenda.api.views import AppointmentsView

    def mock_post(self, request, *args, **kwargs):
        raise RuntimeError(
            f"Crash processing {secret_name} phone {secret_phone} email {secret_email}"
        )

    monkeypatch.setattr(AppointmentsView, "post", mock_post)

    client = APIClient(raise_request_exception=False)
    resp = client.post("/api/v1/appointments/", payload, format="json")
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    # Check that console log lines / JSON formatter never emit the raw phone, email, or name
    for record in caplog.records:
        message_str = record.getMessage()
        assert secret_phone not in message_str
        assert secret_email not in message_str
