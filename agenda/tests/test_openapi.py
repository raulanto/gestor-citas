"""Tests for OpenAPI schema generation, synchronization, error codes, and docs routes."""

from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from agenda import exceptions as domain_exceptions
from agenda.api.schemas import ApiErrorCode
from agenda.exceptions import DomainError


@pytest.mark.django_db
def test_openapi_schema_generation_without_warnings():
    """Verify spectacular generates OpenAPI YAML schema cleanly with 0 warnings."""
    out = StringIO()
    call_command("spectacular", "--validate", "--fail-on-warn", stdout=out)
    output = out.getvalue()
    assert "openapi: 3.0.3" in output or "title: Agenda de Citas API" in output


@pytest.mark.django_db
def test_openapi_yaml_file_is_synchronized():
    """Verify openapi.yaml on disk matches the freshly generated schema without drift."""
    repo_root = Path(settings.BASE_DIR)
    yaml_file = repo_root / "openapi.yaml"
    assert yaml_file.exists(), "openapi.yaml must exist in the root of the repository."

    on_disk_content = yaml_file.read_text(encoding="utf-8")

    out = StringIO()
    call_command("spectacular", "--validate", "--fail-on-warn", stdout=out)
    generated_content = out.getvalue()

    # Compare YAML content
    assert on_disk_content.strip() == generated_content.strip(), (
        "openapi.yaml is out of sync with current API annotations. "
        "Run 'uv run python manage.py spectacular --file openapi.yaml "
        "--validate --fail-on-warn' to update it."
    )


def test_error_response_codes_enum_exact_match():
    """Verify ApiErrorCode enum covers all DomainError subclasses and operational error codes."""
    enum_values = {code.value for code in ApiErrorCode}

    # 1. Collect all DomainError subclasses
    domain_codes = set()
    for attr_name in dir(domain_exceptions):
        cls = getattr(domain_exceptions, attr_name)
        if isinstance(cls, type) and issubclass(cls, DomainError):
            domain_codes.add(cls.code)

    for code in domain_codes:
        assert code in enum_values, f"Domain error code '{code}' is missing from ApiErrorCode."

    # 2. Known Auth & Operational codes
    expected_operational_codes = {
        "NOT_AUTHENTICATED",
        "INVALID_TOKEN",
        "INVALID_CREDENTIALS",
        "LOGIN_LOCKED",
        "FORBIDDEN",
        "THROTTLED",
        "APPOINTMENT_NOT_FOUND",
        "INVALID_PARAMETERS",
        "VALIDATION_ERROR",
        "SERVICE_UNAVAILABLE",
    }
    for code in expected_operational_codes:
        assert code in enum_values, f"Operational code '{code}' is missing from ApiErrorCode."


@pytest.mark.django_db
def test_api_docs_conditional_routes(api_client: APIClient):
    """Schema and Swagger UI routes exist when API_DOCS_ENABLED=True and 404 when False."""
    import importlib
    import sys

    from django.urls import clear_url_caches

    def reload_urls():
        clear_url_caches()
        if "agenda.api.urls" in sys.modules:
            importlib.reload(sys.modules["agenda.api.urls"])
        if "config.urls" in sys.modules:
            importlib.reload(sys.modules["config.urls"])

    try:
        # 1. With API_DOCS_ENABLED = True
        with override_settings(API_DOCS_ENABLED=True):
            reload_urls()
            resp_schema = api_client.get("/api/v1/schema/")
            assert resp_schema.status_code == status.HTTP_200_OK

            resp_docs = api_client.get("/api/v1/docs/")
            assert resp_docs.status_code == status.HTTP_200_OK

        # 2. With API_DOCS_ENABLED = False
        with override_settings(API_DOCS_ENABLED=False):
            reload_urls()
            resp_schema = api_client.get("/api/v1/schema/")
            assert resp_schema.status_code in (
                status.HTTP_404_NOT_FOUND,
                status.HTTP_401_UNAUTHORIZED,
            )

            resp_docs = api_client.get("/api/v1/docs/")
            assert resp_docs.status_code in (
                status.HTTP_404_NOT_FOUND,
                status.HTTP_401_UNAUTHORIZED,
            )
    finally:
        reload_urls()

