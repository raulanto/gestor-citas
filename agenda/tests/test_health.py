"""Tests for health liveness and readiness endpoints."""


import pytest
from django.core.cache import cache
from django.db import connection
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_liveness_endpoint():
    """Verify that GET /api/v1/health/ returns HTTP 200 with status ok (anonymous public)."""
    client = APIClient()
    response = client.get("/api/v1/health/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_health_readiness_healthy():
    """Verify that GET /api/v1/health/ready/ returns HTTP 200 ok when healthy."""
    client = APIClient()
    response = client.get("/api/v1/health/ready/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_health_readiness_db_failure(monkeypatch):
    """When the DB is unavailable, returns 503 unavailable with failing=['database']."""
    client = APIClient()

    def mock_cursor():
        raise RuntimeError("Database connection refused on postgresql://internal.host:5432/db")

    monkeypatch.setattr(connection, "cursor", mock_cursor)

    response = client.get("/api/v1/health/ready/")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert data["status"] == "unavailable"
    assert data["failing"] == ["database"]
    # Ensure no internal error strings or hostnames leaked
    assert "internal.host" not in str(data)
    assert "postgresql://" not in str(data)
    assert "RuntimeError" not in str(data)


@pytest.mark.django_db
def test_health_readiness_cache_failure(monkeypatch):
    """When cache is unavailable, returns 503 unavailable with failing=['cache']."""
    client = APIClient()

    def mock_cache_set(*args, **kwargs):
        raise ConnectionError("Redis server at redis-cluster.internal:6379 is down")

    monkeypatch.setattr(cache, "set", mock_cache_set)

    response = client.get("/api/v1/health/ready/")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert data["status"] == "unavailable"
    assert data["failing"] == ["cache"]
    assert "redis-cluster.internal" not in str(data)
    assert "ConnectionError" not in str(data)


@pytest.mark.django_db
def test_health_readiness_both_failing(monkeypatch):
    """When both database and cache are unavailable, returns failing=['database', 'cache']."""
    client = APIClient()

    def mock_cursor():
        raise Exception("DB down")

    def mock_cache_set(*args, **kwargs):
        raise Exception("Cache down")

    monkeypatch.setattr(connection, "cursor", mock_cursor)
    monkeypatch.setattr(cache, "set", mock_cache_set)

    response = client.get("/api/v1/health/ready/")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert data["status"] == "unavailable"
    assert "database" in data["failing"]
    assert "cache" in data["failing"]
