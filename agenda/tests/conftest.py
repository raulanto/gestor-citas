"""Pytest configuration and shared fixtures for agenda tests."""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from agenda.tests.factories import (
    StaffUserFactory,
    SuperUserFactory,
    UserFactory,
    WorkerUserFactory,
)


@pytest.fixture
def api_client() -> APIClient:
    """Anonymous APIClient."""
    return APIClient()


@pytest.fixture
def staff_user(db):
    """Staff user fixture."""
    return StaffUserFactory()


@pytest.fixture
def super_user(db):
    """Superuser fixture."""
    return SuperUserFactory()


@pytest.fixture
def worker_user(db):
    """Worker user fixture with linked Worker model."""
    return WorkerUserFactory()


@pytest.fixture
def plain_user(db):
    """Normal user fixture without staff or worker profile."""
    return UserFactory()


@pytest.fixture
def auth_client_for_user():
    """Factory helper to obtain an APIClient authenticated with JWT Bearer for a given user."""

    def _auth_client(user) -> APIClient:
        client = APIClient()
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        return client

    return _auth_client


@pytest.fixture
def staff_client(staff_user, auth_client_for_user) -> APIClient:
    """APIClient authenticated as staff."""
    return auth_client_for_user(staff_user)


@pytest.fixture
def worker_client(worker_user, auth_client_for_user) -> APIClient:
    """APIClient authenticated as worker."""
    return auth_client_for_user(worker_user)
