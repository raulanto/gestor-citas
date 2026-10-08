"""API views for managing appointments.

Handles listing, booking, details, cancelling, rescheduling, and completing.
"""

import datetime
import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.filters import AppointmentFilter
from agenda.api.pagination import StandardLimitOffsetPagination
from agenda.api.permissions import IsAppointmentWorkerOrStaff, IsStaff
from agenda.api.roles import Role, get_user_role
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    AppointmentBookingResponseSerializer,
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentRescheduleSerializer,
    RequesterAppointmentDetailSerializer,
    RotateTokenResponseSerializer,
    StaffAppointmentDetailSerializer,
    WorkerAppointmentDetailSerializer,
)
from agenda.api.throttling import (
    BookingContactRateThrottle,
    BookingHourRateThrottle,
    BookingMinuteRateThrottle,
    ManageRateThrottle,
    UserRateThrottle,
)
from agenda.exceptions import ServiceNotFound
from agenda.models import Appointment, Service
from agenda.selectors import get_appointment
from agenda.services import (
    book_appointment,
    cancel_appointment,
    complete_appointment,
    get_or_create_requester,
    mark_no_show,
    reschedule_appointment,
    rotate_manage_token,
)
from agenda.services.manage_token import verify_manage_token


def _get_manage_token_from_request(request: Request) -> str | None:
    token = request.headers.get("X-Manage-Token")
    if not token:
        token = request.META.get("HTTP_X_MANAGE_TOKEN")
    return token.strip() if token else None


class AppointmentsView(APIView):
    """List appointments (Staff only, GET) or book a new appointment (Public, POST)."""

    permission_classes = [AllowAny]

    def get_throttles(self):
        if self.request.method == "POST":
            return [
                BookingMinuteRateThrottle(),
                BookingHourRateThrottle(),
                BookingContactRateThrottle(),
            ]
        return [UserRateThrottle()]

    @extend_schema(
        summary="Listar citas con filtros y paginación (Staff)",
        description=(
            "Permite al personal Staff consultar y filtrar citas por fecha, rango de fechas "
            "(hasta 92 días), estados múltiples, trabajador, servicio, inatendibles y ordenamiento."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=datetime.date,
                description="Filtrar por fecha exacta (YYYY-MM-DD).",
            ),
            OpenApiParameter(
                name="date_from",
                type=datetime.date,
                description="Fecha inicial del rango (YYYY-MM-DD).",
            ),
            OpenApiParameter(
                name="date_to",
                type=datetime.date,
                description="Fecha final del rango (YYYY-MM-DD, máximo 92 días).",
            ),
            OpenApiParameter(
                name="status",
                type=str,
                many=True,
                description="Estado(s) de la cita (ej. CONFIRMED, WAITLISTED).",
            ),
            OpenApiParameter(
                name="worker",
                type=int,
                description="ID del trabajador asignado.",
            ),
            OpenApiParameter(
                name="service",
                type=int,
                description="ID del servicio.",
            ),
            OpenApiParameter(
                name="unserviceable",
                type=bool,
                description="Filtrar solo citas en espera inatendibles.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Ordenamiento: start_at, -start_at, created_at, -created_at.",
            ),
            OpenApiParameter(
                name="limit",
                type=int,
                description="Número de resultados por página (default 25, max 100).",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                description="Desplazamiento inicial para paginación.",
            ),
        ],
        responses={
            200: StaffAppointmentDetailSerializer(many=True),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
    def get(self, request: Request, *args, **kwargs) -> Response:
        role = get_user_role(request.user)
        if role == Role.ANONYMOUS:
            return Response(
                {"code": "NOT_AUTHENTICATED", "detail": "Se requiere autenticación."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if role != Role.STAFF:
            return Response(
                {"code": "FORBIDDEN", "detail": "No tiene permisos de staff para listar citas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        queryset = (
            Appointment.objects.all()
            .select_related(
                "requester",
                "service",
                "worker",
                "worker__user",
                "rescheduled_from",
            )
            .prefetch_related("rescheduled_children")
        )

        filterset = AppointmentFilter(request.query_params, queryset=queryset, request=request)
        if not filterset.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Parámetros de consulta inválidos.",
                    "errors": filterset.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(filterset.qs, request, view=self)
        serializer = StaffAppointmentDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Solicitar nueva cita (Público)",
        description=(
            "Reserva una cita con asignación óptima de personal o colocación en lista de espera. "
            "Devuelve un 'manage_token' de gestión única vez para que el solicitante "
            "administre su cita."
        ),
        request=AppointmentCreateSerializer,
        responses={
            201: AppointmentBookingResponseSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
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

        response_data = AppointmentBookingResponseSerializer(
            result.appointment, context={"manage_token": result.manage_token}
        ).data
        return Response(response_data, status=status.HTTP_201_CREATED)


AppointmentCreateView = AppointmentsView
AppointmentListView = AppointmentsView


class AppointmentDetailView(APIView):
    """Retrieve details for an existing appointment with role-appropriate exposure."""

    permission_classes = [AllowAny]

    def get_throttles(self):
        if self.request.user and self.request.user.is_authenticated:
            return [UserRateThrottle()]
        return [ManageRateThrottle()]

    @extend_schema(
        summary="Detalle de cita por UUID",
        description=(
            "Devuelve el detalle de la cita. El solicitante debe proveer 'X-Manage-Token'. "
            "La exposición de datos personales se segrega por rol (mínima para solicitante, "
            "operativa para trabajador, total para staff)."
        ),
        responses={
            200: StaffAppointmentDetailSerializer,
            401: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
    def get(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        role = get_user_role(request.user)

        if role == Role.STAFF:
            serializer = StaffAppointmentDetailSerializer(appointment)
            return Response(serializer.data, status=status.HTTP_200_OK)

        if role == Role.WORKER:
            worker = getattr(request.user, "worker_profile", None)
            if worker is not None and appointment.worker_id == worker.id:
                serializer = WorkerAppointmentDetailSerializer(appointment)
                return Response(serializer.data, status=status.HTTP_200_OK)

        # Check manage token for requester access
        token = _get_manage_token_from_request(request)
        if token and verify_manage_token(appointment, token):
            serializer = RequesterAppointmentDetailSerializer(appointment)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Uniform 404 to prevent ID enumeration
        return Response(
            {"code": "APPOINTMENT_NOT_FOUND", "detail": "La cita solicitada no existe."},
            status=status.HTTP_404_NOT_FOUND,
        )


class AppointmentCancelView(APIView):
    """Cancel an appointment using manage token or staff force."""

    permission_classes = [AllowAny]

    def get_throttles(self):
        if self.request.user and self.request.user.is_authenticated:
            return [UserRateThrottle()]
        return [ManageRateThrottle()]

    @extend_schema(
        summary="Cancelar cita",
        description=(
            "Cancela una cita liberando el horario y recalculando la lista de espera. "
            "El solicitante requiere 'X-Manage-Token'. Staff puede usar 'force=true'."
        ),
        request=AppointmentCancelSerializer,
        responses={
            200: StaffAppointmentDetailSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        role = get_user_role(request.user)
        is_staff = role == Role.STAFF

        if isinstance(request.data, dict) and request.data.get("force") and not is_staff:
            return Response(
                {
                    "code": "FORBIDDEN",
                    "detail": "Se requieren permisos de staff para forzar la cancelación.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        appointment = get_appointment(id)

        # Authorization: Staff or valid manage token
        token = _get_manage_token_from_request(request)
        has_token = bool(token and verify_manage_token(appointment, token))

        if not is_staff and not has_token:
            return Response(
                {"code": "APPOINTMENT_NOT_FOUND", "detail": "La cita solicitada no existe."},
                status=status.HTTP_404_NOT_FOUND,
            )

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
        if force and not is_staff:
            return Response(
                {
                    "code": "FORBIDDEN",
                    "detail": "Se requieren permisos de staff para forzar la cancelación.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        reason = serializer.validated_data.get("reason", "")
        actor = request.user if request.user and request.user.is_authenticated else None

        updated_appt = cancel_appointment(
            appointment,
            reason=reason,
            actor=actor,
            force=force,
        )

        if is_staff:
            response_serializer = StaffAppointmentDetailSerializer(updated_appt)
        else:
            response_serializer = RequesterAppointmentDetailSerializer(updated_appt)

        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AppointmentRescheduleView(APIView):
    """Reschedule an existing appointment to a new date and time."""

    permission_classes = [AllowAny]

    def get_throttles(self):
        if self.request.user and self.request.user.is_authenticated:
            return [UserRateThrottle()]
        return [ManageRateThrottle()]

    @extend_schema(
        summary="Reprogramar cita",
        description=(
            "Reprograma una cita a un nuevo horario atómicamente. "
            "Devuelve un nuevo 'manage_token' para la nueva cita."
        ),
        request=AppointmentRescheduleSerializer,
        responses={
            201: AppointmentBookingResponseSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        role = get_user_role(request.user)
        is_staff = role == Role.STAFF

        if isinstance(request.data, dict) and request.data.get("force") and not is_staff:
            return Response(
                {
                    "code": "FORBIDDEN",
                    "detail": "Se requieren permisos de staff para forzar la reprogramación.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        appointment = get_appointment(id)

        token = _get_manage_token_from_request(request)
        has_token = bool(token and verify_manage_token(appointment, token))

        if not is_staff and not has_token:
            return Response(
                {"code": "APPOINTMENT_NOT_FOUND", "detail": "La cita solicitada no existe."},
                status=status.HTTP_404_NOT_FOUND,
            )

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
        if force and not is_staff:
            return Response(
                {
                    "code": "FORBIDDEN",
                    "detail": "Se requieren permisos de staff para forzar la reprogramación.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

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

        response_data = AppointmentBookingResponseSerializer(
            result.appointment, context={"manage_token": result.manage_token}
        ).data
        return Response(response_data, status=status.HTTP_201_CREATED)


class AppointmentCompleteView(APIView):
    """Mark a confirmed appointment as completed (Worker or Staff)."""

    permission_classes = [IsAppointmentWorkerOrStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Marcar cita como completada",
        description=(
            "Transiciona una cita CONFIRMED a COMPLETADA (solo trabajador asignado o staff)."
        ),
        request=None,
        responses={
            200: WorkerAppointmentDetailSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        self.check_object_permissions(request, appointment)

        actor = request.user if request.user and request.user.is_authenticated else None
        updated_appt = complete_appointment(appointment, actor=actor)

        role = get_user_role(request.user)
        if role == Role.STAFF:
            serializer = StaffAppointmentDetailSerializer(updated_appt)
        else:
            serializer = WorkerAppointmentDetailSerializer(updated_appt)

        return Response(serializer.data, status=status.HTTP_200_OK)


class AppointmentNoShowView(APIView):
    """Mark a confirmed appointment as no-show (Worker or Staff)."""

    permission_classes = [IsAppointmentWorkerOrStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Marcar inasistencia de cita",
        description="Transiciona una cita CONFIRMED a NO_SHOW (solo trabajador asignado o staff).",
        request=None,
        responses={
            200: WorkerAppointmentDetailSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        self.check_object_permissions(request, appointment)

        actor = request.user if request.user and request.user.is_authenticated else None
        updated_appt = mark_no_show(appointment, actor=actor)

        role = get_user_role(request.user)
        if role == Role.STAFF:
            serializer = StaffAppointmentDetailSerializer(updated_appt)
        else:
            serializer = WorkerAppointmentDetailSerializer(updated_appt)

        return Response(serializer.data, status=status.HTTP_200_OK)


class AppointmentRotateTokenView(APIView):
    """Rotate the manage token for an appointment (Staff only)."""

    permission_classes = [IsStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Rotar token de gestión de cita (Staff)",
        description=(
            "Genera un nuevo token de gestión para la cita e invalida el anterior "
            "registrando auditoría."
        ),
        request=None,
        responses={
            200: RotateTokenResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Citas"],
    )
    def post(self, request: Request, id: uuid.UUID, *args, **kwargs) -> Response:
        appointment = get_appointment(id)
        new_token = rotate_manage_token(appointment, actor=request.user)
        serializer = RotateTokenResponseSerializer(
            {"appointment_id": appointment.id, "manage_token": new_token}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
