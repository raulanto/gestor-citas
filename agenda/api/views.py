"""API views for agenda microapp."""

import uuid

from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.serializers import (
    AppointmentCreateSerializer,
    AppointmentDetailSerializer,
    AvailabilityQuerySerializer,
    DayAvailabilitySerializer,
    WaitlistEntrySerializer,
    WaitlistQuerySerializer,
)
from agenda.exceptions import ServiceNotFound
from agenda.models import Service
from agenda.selectors import get_appointment, get_day_availability, list_waitlist
from agenda.services import book_appointment, get_or_create_requester


class HealthCheckView(APIView):
    """Health check endpoint confirming API availability."""

    authentication_classes = []
    permission_classes = []

    def get(self, request: Request, *args, **kwargs) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class AvailabilityView(APIView):
    """Query available appointment slots and daily capacity for a service on a given date."""

    authentication_classes = []
    permission_classes = []

    def get(self, request: Request, *args, **kwargs) -> Response:
        query_serializer = AvailabilityQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Parámetros de consulta inválidos.",
                    "errors": query_serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_date = query_serializer.validated_data["date"]
        service_id = query_serializer.validated_data["service"]

        service = Service.objects.filter(id=service_id, is_active=True).first()
        if service is None:
            raise ServiceNotFound()

        availability = get_day_availability(target_date, service)
        response_data = {
            "date": availability.date,
            "service": service,
            "is_open": availability.is_open,
            "reason": availability.reason,
            "effective_quota": availability.effective_quota,
            "remaining_quota": availability.remaining_quota,
            "slots": availability.slots,
        }
        response_serializer = DayAvailabilitySerializer(response_data)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AppointmentCreateView(APIView):
    """Create and book a new appointment or place on the waitlist."""

    authentication_classes = []
    permission_classes = []

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = AppointmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de solicitud inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        requester_data = serializer.validated_data["requester"]
        requester = get_or_create_requester(
            full_name=requester_data["full_name"],
            phone=requester_data.get("phone"),
            email=requester_data.get("email"),
        )

        service_id = serializer.validated_data["service"]
        service = Service.objects.filter(id=service_id, is_active=True).first()
        if service is None:
            raise ServiceNotFound()

        start_at = serializer.validated_data["start_at"]
        actor = request.user if request.user.is_authenticated else None

        result = book_appointment(
            requester=requester,
            service=service,
            start_at=start_at,
            actor=actor,
        )

        response_serializer = AppointmentDetailSerializer(result.appointment)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class AppointmentDetailView(APIView):
    """Retrieve details for an existing appointment."""

    authentication_classes = []
    permission_classes = []

    def get(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        serializer = AppointmentDetailSerializer(appointment)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WaitlistView(APIView):
    """List waitlisted appointments for a specific date in FIFO order (Staff only)."""

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request: Request, *args, **kwargs) -> Response:
        query_serializer = WaitlistQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Parámetros de consulta inválidos.",
                    "errors": query_serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_date = query_serializer.validated_data["date"]
        entries = list_waitlist(target_date)
        serializer = WaitlistEntrySerializer(entries, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
