"""Tests for minimal personal data exposure per role."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from agenda.tests.factories import (
    RequesterFactory,
    WorkerUserFactory,
    create_appointment_with_token,
)


@pytest.mark.django_db
class TestPersonalDataExposureByRole:
    """Validate that personal data (phone, email) is strictly filtered based on caller role."""

    def test_requester_view_has_no_phone_and_no_email(self, api_client: APIClient):
        requester = RequesterFactory(
            full_name="Carlos Ruiz",
            phone="5559876543",
            email="carlos@example.com",
        )
        appointment, token = create_appointment_with_token(requester=requester)

        response = api_client.get(
            f"/api/v1/appointments/{appointment.id}/",
            HTTP_X_MANAGE_TOKEN=token,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        requester_data = data["requester"]

        assert requester_data["full_name"] == "Carlos Ruiz"
        assert "phone" not in requester_data
        assert "email" not in requester_data

    def test_worker_view_has_name_and_phone_but_no_email(self, auth_client_for_user):
        worker_user = WorkerUserFactory()
        worker = worker_user.worker_profile
        client = auth_client_for_user(worker_user)

        requester = RequesterFactory(
            full_name="Maria Lopez",
            phone="5551234567",
            email="maria@example.com",
        )
        appointment, _ = create_appointment_with_token(worker=worker, requester=requester)

        response = client.get(f"/api/v1/appointments/{appointment.id}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        requester_data = data["requester"]

        assert requester_data["full_name"] == "Maria Lopez"
        assert requester_data["phone"] == "5551234567"
        assert "email" not in requester_data

    def test_worker_cannot_view_unassigned_appointment_without_token(self, auth_client_for_user):
        worker_user1 = WorkerUserFactory()
        worker_user2 = WorkerUserFactory()
        client1 = auth_client_for_user(worker_user1)

        appointment, _ = create_appointment_with_token(worker=worker_user2.worker_profile)

        # Worker 1 tries to view Worker 2's appointment without token -> 404
        response = client1.get(f"/api/v1/appointments/{appointment.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_staff_view_has_full_details_including_email(self, staff_client: APIClient):
        requester = RequesterFactory(
            full_name="Elena Gomez",
            phone="5554443322",
            email="elena@example.com",
        )
        appointment, _ = create_appointment_with_token(requester=requester)

        response = staff_client.get(f"/api/v1/appointments/{appointment.id}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        requester_data = data["requester"]

        assert requester_data["full_name"] == "Elena Gomez"
        assert requester_data["phone"] == "5554443322"
        assert requester_data["email"] == "elena@example.com"
