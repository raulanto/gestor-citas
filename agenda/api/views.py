"""API views for agenda microapp."""

import uuid

from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.serializers import (
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentDetailSerializer,
    AppointmentListQuerySerializer,
    AppointmentRescheduleSerializer,
    AvailabilityQuerySerializer,
    DayAvailabilitySerializer,
    WaitlistEntrySerializer,
    WaitlistQuerySerializer,
)
from agenda.exceptions import ServiceNotFound
from agenda.models import Service
from agenda.selectors import (
    get_appointment,
    get_day_availability,
    list_appointments_queryset,
    list_waitlist,
)
from agenda.services import (
    book_appointment,
    cancel_appointment,
    complete_appointment,
    get_or_create_requester,
    mark_no_show,
    reschedule_appointment,
)


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


class AppointmentsView(APIView):
    """List appointments (Staff only, GET) or book a new appointment (Public, POST)."""

    authentication_classes = [SessionAuthentication, BasicAuthentication]

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAdminUser()]
        return []

    def get(self, request: Request, *args, **kwargs) -> Response:
        query_serializer = AppointmentListQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Parámetros de consulta inválidos.",
                    "errors": query_serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_date = query_serializer.validated_data.get("date")
        status_filter = query_serializer.validated_data.get("status")

        qs = list_appointments_queryset(target_date=target_date, status_filter=status_filter)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AppointmentDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

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


AppointmentCreateView = AppointmentsView
AppointmentListView = AppointmentsView


class AppointmentDetailView(APIView):
    """Retrieve details for an existing appointment."""

    authentication_classes = []
    permission_classes = []

    def get(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        serializer = AppointmentDetailSerializer(appointment)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AppointmentCancelView(APIView):
    """Cancel an appointment using its UUID (or staff forced)."""

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = []

    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        serializer = AppointmentCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de cancelación inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        force = serializer.validated_data.get("force", False)
        if force and not (request.user and request.user.is_authenticated and request.user.is_staff):
            return Response(
                {
                    "code": "PERMISSION_DENIED",
                    "detail": "Se requieren permisos de staff para forzar la cancelación.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        appointment = get_appointment(id)
        reason = serializer.validated_data.get("reason", "")
        actor = request.user if request.user and request.user.is_authenticated else None

        updated_appt = cancel_appointment(
            appointment,
            reason=reason,
            actor=actor,
            force=force,
        )
        response_serializer = AppointmentDetailSerializer(updated_appt)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AppointmentRescheduleView(APIView):
    """Reschedule an existing appointment to a new date and time."""

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = []

    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        serializer = AppointmentRescheduleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de reprogramación inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        force = serializer.validated_data.get("force", False)
        if force and not (request.user and request.user.is_authenticated and request.user.is_staff):
            return Response(
                {
                    "code": "PERMISSION_DENIED",
                    "detail": "Se requieren permisos de staff para forzar la reprogramación.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        appointment = get_appointment(id)
        new_start_at = serializer.validated_data["start_at"]
        allow_waitlist = serializer.validated_data.get("allow_waitlist", False)
        actor = request.user if request.user and request.user.is_authenticated else None

        result = reschedule_appointment(
            appointment,
            new_start_at=new_start_at,
            actor=actor,
            force=force,
            allow_waitlist=allow_waitlist,
        )
        response_serializer = AppointmentDetailSerializer(result.appointment)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class AppointmentCompleteView(APIView):
    """Mark a confirmed appointment as completed (Staff only)."""

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        actor = request.user if request.user and request.user.is_authenticated else None
        updated_appt = complete_appointment(appointment, actor=actor)
        serializer = AppointmentDetailSerializer(updated_appt)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AppointmentNoShowView(APIView):
    """Mark a confirmed appointment as no-show (Staff only)."""

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        actor = request.user if request.user and request.user.is_authenticated else None
        updated_appt = mark_no_show(appointment, actor=actor)
        serializer = AppointmentDetailSerializer(updated_appt)
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
