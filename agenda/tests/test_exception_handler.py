import pytest
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from agenda.api.exception_handler import custom_exception_handler
from agenda.exceptions import (
    AppointmentNotFound,
    CancellationNotAllowed,
    DayClosed,
    DomainError,
    InvalidDuration,
    InvalidSlot,
    InvalidStateTransition,
    NoWorkerAvailable,
    OutsideBookingWindow,
    QuotaExceeded,
    RequesterLimitReached,
    RescheduleLimitReached,
    ScheduleConflict,
    ServiceNotFound,
    WaitlistFull,
)


@pytest.fixture
def drf_context():
    factory = APIRequestFactory()
    request = factory.get("/api/v1/fake-endpoint/")
    return {"request": Request(request), "view": None}


def test_base_domain_error_handled(drf_context):
    exc = DomainError()
    response = custom_exception_handler(exc, drf_context)

    assert response is not None
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {
        "code": "domain_error",
        "detail": "Ha ocurrido un error en la lógica de negocio.",
    }


def test_custom_domain_error_attributes(drf_context):
    exc = DomainError(detail="Mensaje personalizado", code="custom_code", http_status=422)
    response = custom_exception_handler(exc, drf_context)

    assert response is not None
    assert response.status_code == 422
    assert response.data == {
        "code": "custom_code",
        "detail": "Mensaje personalizado",
    }


@pytest.mark.parametrize(
    "exception_cls,expected_code,expected_status",
    [
        (DayClosed, "day_closed", status.HTTP_409_CONFLICT),
        (QuotaExceeded, "quota_exceeded", status.HTTP_409_CONFLICT),
        (NoWorkerAvailable, "no_worker_available", status.HTTP_409_CONFLICT),
        (CancellationNotAllowed, "cancellation_not_allowed", status.HTTP_409_CONFLICT),
        (RescheduleLimitReached, "reschedule_limit_reached", status.HTTP_409_CONFLICT),
        (InvalidStateTransition, "invalid_state_transition", status.HTTP_409_CONFLICT),
        (InvalidDuration, "invalid_duration", status.HTTP_400_BAD_REQUEST),
        (ScheduleConflict, "schedule_conflict", status.HTTP_409_CONFLICT),
        (InvalidSlot, "invalid_slot", status.HTTP_400_BAD_REQUEST),
        (OutsideBookingWindow, "outside_booking_window", status.HTTP_400_BAD_REQUEST),
        (RequesterLimitReached, "requester_limit_reached", status.HTTP_409_CONFLICT),
        (WaitlistFull, "waitlist_full", status.HTTP_409_CONFLICT),
        (AppointmentNotFound, "appointment_not_found", status.HTTP_404_NOT_FOUND),
        (ServiceNotFound, "service_not_found", status.HTTP_404_NOT_FOUND),
    ],
)
def test_domain_exception_subclasses(exception_cls, expected_code, expected_status, drf_context):
    exc = exception_cls()
    response = custom_exception_handler(exc, drf_context)

    assert response is not None
    assert response.status_code == expected_status
    assert response.data["code"] == expected_code
    assert isinstance(response.data["detail"], str)
    assert len(response.data["detail"]) > 0


def test_delegates_standard_drf_exceptions(drf_context):
    exc = drf_exceptions.NotFound("Recurso no encontrado.")
    response = custom_exception_handler(exc, drf_context)

    assert response is not None
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_unhandled_non_drf_exceptions_return_none(drf_context):
    exc = ValueError("Unhandled python error")
    response = custom_exception_handler(exc, drf_context)

    assert response is None
