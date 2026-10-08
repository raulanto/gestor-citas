"""Tests for application-level rate throttling in agenda microapp."""

import datetime

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from agenda.tests.factories import (
    DayConfigFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_throttling_disabled_by_default_in_test_env(api_client: APIClient):
    """When THROTTLING_ENABLED is False (default in test.py), unlimited requests are allowed."""
    with override_settings(THROTTLING_ENABLED=False):
        for _ in range(15):
            resp = api_client.get("/api/v1/availability/?service=1&date=2026-10-15")
            assert resp.status_code != status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
def test_availability_throttling_and_429_format(api_client: APIClient):
    """Exceeding availability throttle returns 429 with error payload and Retry-After header."""
    service = ServiceFactory(duration_minutes=30, is_active=True)
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].copy()
    rates["availability"] = "3/min"

    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates},
    ):
        for _ in range(3):
            resp = api_client.get(
                f"/api/v1/availability/?service={service.id}&date=2026-10-15"
            )
            assert resp.status_code == status.HTTP_200_OK

        # 4th request must be throttled
        resp = api_client.get(f"/api/v1/availability/?service={service.id}&date=2026-10-15")
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        data = resp.json()
        assert data["code"] == "THROTTLED"
        assert "detail" in data
        assert "Retry-After" in resp.headers


@pytest.mark.django_db
def test_auth_throttling(api_client: APIClient):
    """Exceeding auth throttle returns 429."""
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].copy()
    rates["auth"] = "2/min"

    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates},
    ):
        for _ in range(2):
            resp = api_client.post(
                "/api/v1/auth/token/",
                {"username": "nonexistent", "password": "wrongpassword"},
            )
            assert resp.status_code in (
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_400_BAD_REQUEST,
            )

        resp = api_client.post(
            "/api/v1/auth/token/",
            {"username": "nonexistent", "password": "wrongpassword"},
        )
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert resp.json()["code"] == "THROTTLED"


@pytest.mark.django_db
def test_user_throttling_by_user_id(api_client: APIClient, staff_user):
    """Authenticated user throttle limits by user id."""
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].copy()
    rates["user"] = "2/min"

    api_client.force_authenticate(user=staff_user)

    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates},
    ):
        for _ in range(2):
            resp = api_client.get("/api/v1/auth/me/")
            assert resp.status_code == status.HTTP_200_OK

        resp = api_client.get("/api/v1/auth/me/")
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert resp.json()["code"] == "THROTTLED"


@pytest.mark.django_db
def test_booking_contact_throttling_normalized_variations(api_client: APIClient):
    """Booking requests with different telephone formatting share the same contact quota."""
    service = ServiceFactory(duration_minutes=30, is_active=True)
    worker = WorkerFactory(is_active=True)
    WorkScheduleFactory(
        worker=worker,
        weekday=3,  # Thursday
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    DayConfigFactory(
        date=datetime.date(2026, 10, 15),
        weekday=None,
        is_open=True,
        max_appointments=10,
    )

    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].copy()
    rates["booking_contact"] = "2/hour"
    rates["booking_minute"] = "100/min"
    rates["booking_hour"] = "100/hour"

    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates},
    ):
        phone_variations = [
            "+52 993 123 4567",
            "9931234567",
            "993-123-4567",
        ]

        payload_1 = {
            "service": service.id,
            "start_at": "2026-10-15T10:00:00-06:00",
            "requester": {
                "full_name": "Carlos Gomez",
                "phone": phone_variations[0],
            },
        }
        resp1 = api_client.post("/api/v1/appointments/", payload_1, format="json")
        assert resp1.status_code in (status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST)

        payload_2 = {
            "service": service.id,
            "start_at": "2026-10-15T11:00:00-06:00",
            "requester": {
                "full_name": "Carlos Gomez",
                "phone": phone_variations[1],
            },
        }
        resp2 = api_client.post(
            "/api/v1/appointments/",
            payload_2,
            format="json",
            REMOTE_ADDR="192.168.1.50",
        )
        assert resp2.status_code in (
            status.HTTP_201_CREATED,
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_409_CONFLICT,
        )

        # 3rd request with 3rd phone variation must be throttled by contact
        payload_3 = {
            "service": service.id,
            "start_at": "2026-10-15T12:00:00-06:00",
            "requester": {
                "full_name": "Carlos Gomez",
                "phone": phone_variations[2],
            },
        }
        resp3 = api_client.post(
            "/api/v1/appointments/",
            payload_3,
            format="json",
            REMOTE_ADDR="192.168.1.99",
        )
        assert resp3.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert resp3.json()["code"] == "THROTTLED"


@pytest.mark.django_db
def test_cache_keys_contain_no_raw_pii(api_client: APIClient):
    """Verify that throttle cache keys never contain raw phone, email, or full name."""
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].copy()
    rates["booking_contact"] = "5/hour"

    raw_phone = "+52 993 987 6543"
    raw_email = "sensitive.user@example.com"
    raw_name = "Maria Perez"

    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates},
    ):
        payload = {
            "service": 999,
            "start_at": "2026-10-15T10:00:00-06:00",
            "requester": {
                "full_name": raw_name,
                "phone": raw_phone,
                "email": raw_email,
            },
        }
        api_client.post("/api/v1/appointments/", payload, format="json")

        # Inspect LocMemCache storage
        cache_dict = getattr(cache, "_cache", {})
        for key in cache_dict:
            assert raw_phone not in str(key), f"Raw phone found in cache key: {key}"
            assert "9939876543" not in str(key), f"Normalized phone found in cache key: {key}"
            assert raw_email not in str(key), f"Raw email found in cache key: {key}"
            assert raw_name not in str(key), f"Raw name found in cache key: {key}"


@pytest.mark.django_db
def test_trusted_proxies_count_behavior(api_client: APIClient):
    """TRUSTED_PROXIES_COUNT=0 ignores X-Forwarded-For; NUM_PROXIES=1 parses it."""
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].copy()
    rates["availability"] = "1/min"

    # 1. With NUM_PROXIES = 0
    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={
            **settings.REST_FRAMEWORK,
            "DEFAULT_THROTTLE_RATES": rates,
            "NUM_PROXIES": 0,
        },
    ):
        cache.clear()
        resp1 = api_client.get(
            "/api/v1/availability/?service=1&date=2026-10-15",
            HTTP_X_FORWARDED_FOR="203.0.113.195",
            REMOTE_ADDR="127.0.0.1",
        )
        assert resp1.status_code != status.HTTP_429_TOO_MANY_REQUESTS

        resp2 = api_client.get(
            "/api/v1/availability/?service=1&date=2026-10-15",
            HTTP_X_FORWARDED_FOR="198.51.100.10",
            REMOTE_ADDR="127.0.0.1",
        )
        assert resp2.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # 2. With NUM_PROXIES = 1
    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={
            **settings.REST_FRAMEWORK,
            "DEFAULT_THROTTLE_RATES": rates,
            "NUM_PROXIES": 1,
        },
    ):
        cache.clear()
        resp1 = api_client.get(
            "/api/v1/availability/?service=1&date=2026-10-15",
            HTTP_X_FORWARDED_FOR="203.0.113.195",
            REMOTE_ADDR="127.0.0.1",
        )
        assert resp1.status_code != status.HTTP_429_TOO_MANY_REQUESTS

        resp2 = api_client.get(
            "/api/v1/availability/?service=1&date=2026-10-15",
            HTTP_X_FORWARDED_FOR="198.51.100.10",
            REMOTE_ADDR="127.0.0.1",
        )
        assert resp2.status_code != status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
def test_health_endpoints_have_no_application_throttle(api_client: APIClient):
    """Health liveness and readiness endpoints are never throttled."""
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].copy()

    with override_settings(
        THROTTLING_ENABLED=True,
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates},
    ):
        for _ in range(30):
            resp1 = api_client.get("/api/v1/health/")
            assert resp1.status_code == status.HTTP_200_OK

            resp2 = api_client.get("/api/v1/health/ready/")
            assert resp2.status_code == status.HTTP_200_OK
