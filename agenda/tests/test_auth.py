"""Tests for authentication, JWT lifecycle, lockout, and user profile."""

import time

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from agenda.tests.factories import (
    StaffUserFactory,
    UserFactory,
    WorkerFactory,
)


@pytest.mark.django_db
class TestLoginAndLockout:
    """Test login authentication, invalid credentials, and brute-force lockout."""

    def setup_method(self):
        cache.clear()

    def test_successful_login_returns_tokens(self, api_client: APIClient):
        UserFactory(username="juan_staff", is_staff=True, password="correct_password")

        response = api_client.post(
            "/api/v1/auth/token/",
            {"username": "juan_staff", "password": "correct_password"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access" in data
        assert "refresh" in data

    def test_invalid_password_returns_401_uniform(self, api_client: APIClient):
        UserFactory(username="juan", password="correct_password")

        response = api_client.post(
            "/api/v1/auth/token/",
            {"username": "juan", "password": "wrong_password"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json() == {
            "code": "INVALID_CREDENTIALS",
            "detail": "Credenciales de acceso inválidas.",
        }

    def test_nonexistent_user_returns_same_401_error(self, api_client: APIClient):
        response = api_client.post(
            "/api/v1/auth/token/",
            {"username": "non_existent_user", "password": "any_password"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json() == {
            "code": "INVALID_CREDENTIALS",
            "detail": "Credenciales de acceso inválidas.",
        }

    def test_inactive_user_cannot_login(self, api_client: APIClient):
        UserFactory(username="inactive_user", is_active=False, password="password123")

        response = api_client.post(
            "/api/v1/auth/token/",
            {"username": "inactive_user", "password": "password123"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json() == {
            "code": "INVALID_CREDENTIALS",
            "detail": "Credenciales de acceso inválidas.",
        }

    def test_lockout_after_max_failed_attempts(self, api_client: APIClient, settings):
        settings.LOGIN_MAX_FAILED_ATTEMPTS = 3
        settings.LOGIN_LOCKOUT_MINUTES = 10
        username = "target_user"
        UserFactory(username=username, password="correct_password")

        # 1st and 2nd failed attempts
        for _ in range(2):
            resp = api_client.post(
                "/api/v1/auth/token/",
                {"username": username, "password": "wrong_password"},
                format="json",
            )
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED

        # 3rd failed attempt triggers lockout
        resp = api_client.post(
            "/api/v1/auth/token/",
            {"username": username, "password": "wrong_password"},
            format="json",
        )
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert resp.json() == {
            "code": "LOGIN_LOCKED",
            "detail": "Demasiados intentos fallidos. Intente más tarde.",
        }
        assert "Retry-After" in resp.headers

        # Subsequent attempt even with correct password is still locked
        resp = api_client.post(
            "/api/v1/auth/token/",
            {"username": username, "password": "correct_password"},
            format="json",
        )
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert resp.json()["code"] == "LOGIN_LOCKED"

    def test_lockout_works_for_nonexistent_user(self, api_client: APIClient, settings):
        settings.LOGIN_MAX_FAILED_ATTEMPTS = 3
        username = "ghost_user"

        for _ in range(3):
            resp = api_client.post(
                "/api/v1/auth/token/",
                {"username": username, "password": "wrong_password"},
                format="json",
            )

        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert resp.json()["code"] == "LOGIN_LOCKED"

    def test_successful_login_resets_attempt_counter(self, api_client: APIClient, settings):
        settings.LOGIN_MAX_FAILED_ATTEMPTS = 3
        username = "reset_user"
        UserFactory(username=username, password="correct_password")

        # 2 failures
        for _ in range(2):
            api_client.post(
                "/api/v1/auth/token/",
                {"username": username, "password": "wrong_password"},
                format="json",
            )

        # 1 success resets counter
        resp = api_client.post(
            "/api/v1/auth/token/",
            {"username": username, "password": "correct_password"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK

        # 2 more failures should not lock out
        for _ in range(2):
            resp = api_client.post(
                "/api/v1/auth/token/",
                {"username": username, "password": "wrong_password"},
                format="json",
            )
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestTokenLifecycle:
    """Test refresh token rotation, blacklisting, and logout."""

    def test_token_refresh_with_rotation(self, api_client: APIClient):
        user = UserFactory()
        refresh = RefreshToken.for_user(user)
        raw_refresh = str(refresh)

        # Small pause so iat/exp differ
        time.sleep(0.01)

        response = api_client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": raw_refresh},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access" in data
        assert "refresh" in data
        new_refresh = data["refresh"]
        assert new_refresh != raw_refresh

        # Using the old rotated refresh token fails (it was blacklisted)
        reuse_response = api_client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": raw_refresh},
            format="json",
        )
        assert reuse_response.status_code == status.HTTP_401_UNAUTHORIZED
        assert reuse_response.json()["code"] == "INVALID_TOKEN"

    def test_logout_blacklists_token(self, api_client: APIClient):
        user = UserFactory()
        refresh = RefreshToken.for_user(user)
        raw_refresh = str(refresh)

        # Logout is public and returns 204
        logout_response = api_client.post(
            "/api/v1/auth/logout/",
            {"refresh": raw_refresh},
            format="json",
        )
        assert logout_response.status_code == status.HTTP_204_NO_CONTENT

        # Attempting to refresh with blacklisted token fails
        refresh_response = api_client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": raw_refresh},
            format="json",
        )
        assert refresh_response.status_code == status.HTTP_401_UNAUTHORIZED
        assert refresh_response.json()["code"] == "INVALID_TOKEN"

    def test_invalid_or_corrupt_refresh_token(self, api_client: APIClient):
        response = api_client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": "invalid.jwt.token"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["code"] == "INVALID_TOKEN"


@pytest.mark.django_db
class TestMeEndpoint:
    """Test GET /api/v1/auth/me/ profile and role reporting."""

    def test_anonymous_access_returns_401(self, api_client: APIClient):
        response = api_client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["code"] == "NOT_AUTHENTICATED"

    def test_staff_role(self, staff_client: APIClient, staff_user: User):
        response = staff_client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": staff_user.id,
            "username": staff_user.username,
            "role": "STAFF",
            "worker_id": None,
        }

    def test_worker_role(self, worker_client: APIClient, worker_user: User):
        response = worker_client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": worker_user.id,
            "username": worker_user.username,
            "role": "WORKER",
            "worker_id": worker_user.worker_profile.id,
        }

    def test_staff_with_worker_profile_retains_staff_role(self, auth_client_for_user):
        user = StaffUserFactory(username="staff_doc")
        worker = WorkerFactory(user=user, full_name="Dr. Staff")
        client = auth_client_for_user(user)

        response = client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": user.id,
            "username": user.username,
            "role": "STAFF",
            "worker_id": worker.id,
        }

    def test_superuser_role(self, auth_client_for_user, super_user: User):
        client = auth_client_for_user(super_user)
        response = client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": super_user.id,
            "username": super_user.username,
            "role": "STAFF",
            "worker_id": None,
        }

    def test_plain_user_without_role(self, auth_client_for_user, plain_user: User):
        client = auth_client_for_user(plain_user)
        response = client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": plain_user.id,
            "username": plain_user.username,
            "role": "NONE",
            "worker_id": None,
        }
