import pytest
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_check_endpoint():
    """Verify that GET /api/v1/health/ returns HTTP 200 with status ok."""
    client = APIClient()
    response = client.get("/api/v1/health/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}
