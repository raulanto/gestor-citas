"""API views for agenda microapp."""

import datetime
import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.filters import AppointmentFilter
from agenda.api.pagination import StandardLimitOffsetPagination
from agenda.api.permissions import (
    IsAppointmentWorkerOrStaff,
    IsStaff,
    IsWorkerSelfOrStaff,
)
from agenda.api.roles import Role, get_user_role
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    AppointmentBookingResponseSerializer,
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentRescheduleSerializer,
    AvailabilityQuerySerializer,
    DayAvailabilitySerializer,
    DayConfigDetailSerializer,
    DayConfigSummaryResponseSerializer,
    DayConfigUpdateSerializer,
    RequesterAppointmentDetailSerializer,
    RotateTokenResponseSerializer,
    ScheduleChangeResponseSerializer,
    ScheduleExceptionCreateSerializer,
    StaffAppointmentDetailSerializer,
    WaitlistEntrySerializer,
    WaitlistQuerySerializer,
    WorkerAgendaAppointmentSerializer,
    WorkerAgendaQuerySerializer,
    WorkerAppointmentDetailSerializer,
    WorkerPatchSerializer,
    WorkerScheduleDetailSerializer,
    WorkScheduleSetSerializer,
)
from agenda.api.throttling import (
    AvailabilityRateThrottle,
    BookingContactRateThrottle,
    BookingHourRateThrottle,
    BookingMinuteRateThrottle,
    ManageRateThrottle,
    UserRateThrottle,
)
from agenda.exceptions import ServiceNotFound, WorkerNotFound
from agenda.models import Appointment, DayConfig, ScheduleException, Service, Worker
from agenda.selectors import (
    get_appointment,
    get_day_availability,
    get_day_config_summary,
    get_worker_schedule,
    list_active_appointments,
    list_waitlist,
    list_worker_agenda,
)
from agenda.services import (
    add_exception,
    book_appointment,
    cancel_appointment,
    complete_appointment,
    get_or_create_requester,
    mark_no_show,
    remove_exception,
    reschedule_appointment,
    rotate_manage_token,
    schedule_waitlist_processing,
    set_weekly_schedule,
    set_worker_active,
)
from agenda.services.manage_token import verify_manage_token


def _get_manage_token_from_request(request: Request) -> str | None:
    token = request.headers.get("X-Manage-Token")
    if not token:
        token = request.META.get("HTTP_X_MANAGE_TOKEN")
    return token.strip() if token else None


class AvailabilityView(APIView):
    """Query available appointment slots and daily capacity for a service on a given date."""

    permission_classes = [AllowAny]
    throttle_classes = [AvailabilityRateThrottle]

    @extend_schema(
        summary="Consultar disponibilidad y cupos de un día",
        description="Calcula los intervalos horarios libres y el cupo restante para un servicio en una fecha.",
        parameters=[AvailabilityQuerySerializer],
        responses={
            200: DayAvailabilitySerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Disponibilidad"],
    )
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
            "Devuelve un 'manage_token' de gestión única vez para que el solicitante administre su cita."
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
        description="Transiciona una cita CONFIRMED a COMPLETADA (solo trabajador asignado o staff).",
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
        description="Genera un nuevo token de gestión para la cita e invalida el anterior registrando auditoría.",
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


class WaitlistView(APIView):
    """List waitlisted appointments for a specific date in FIFO order (Staff only)."""

    permission_classes = [IsStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Listar lista de espera FIFO del día (Staff)",
        description="Consulta las citas en estado WAITLISTED de una fecha en orden FIFO con posición absoluta.",
        parameters=[WaitlistQuerySerializer],
        responses={
            200: WaitlistEntrySerializer(many=True),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Lista de Espera"],
    )
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

        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(entries, request, view=self)
        serializer = WaitlistEntrySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class WorkerAgendaView(APIView):
    """Retrieve daily confirmed agenda for a worker."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Consultar agenda del trabajador",
        description="Consulta las citas CONFIRMED del día con datos de contacto del solicitante para el trabajador.",
        parameters=[WorkerAgendaQuerySerializer],
        responses={
            200: WorkerAgendaAppointmentSerializer(many=True),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Agenda del Personal"],
    )
    def get(self, request: Request, *args, **kwargs) -> Response:
        query_serializer = WorkerAgendaQuerySerializer(data=request.query_params)
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
        query_worker_id = query_serializer.validated_data.get("worker_id")
        role = get_user_role(request.user)

        if role == Role.WORKER:
            worker = getattr(request.user, "worker_profile", None)
            if query_worker_id is not None and query_worker_id != worker.id:
                return Response(
                    {
                        "code": "FORBIDDEN",
                        "detail": "Un trabajador no puede consultar la agenda de otro trabajador.",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            effective_worker_id = worker.id

        elif role == Role.STAFF:
            if query_worker_id is None:
                return Response(
                    {
                        "code": "INVALID_PARAMETERS",
                        "detail": "El parámetro 'worker_id' es obligatorio para staff.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            worker = Worker.objects.filter(id=query_worker_id).first()
            if worker is None:
                raise WorkerNotFound()
            effective_worker_id = worker.id

        else:
            return Response(
                {"code": "FORBIDDEN", "detail": "No tiene permisos para consultar la agenda."},
                status=status.HTTP_403_FORBIDDEN,
            )

        appts = list_worker_agenda(effective_worker_id, target_date)
        serializer = WorkerAgendaAppointmentSerializer(appts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Schedule Management API Views
# ---------------------------------------------------------------------------


class WorkerScheduleView(APIView):
    """View and replace a worker's weekly work schedule."""

    permission_classes = [IsWorkerSelfOrStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Consultar horario semanal de trabajador",
        description="Consulta los turnos y descansos semanales de un trabajador junto a sus excepciones futuras.",
        responses={
            200: WorkerScheduleDetailSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Horarios y Excepciones"],
    )
    def get(self, request: Request, id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        schedule_data = get_worker_schedule(worker)
        serializer = WorkerScheduleDetailSerializer(schedule_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Actualizar horario semanal de trabajador",
        description="Reemplaza el horario semanal revalidando citas futuras y admitiendo dry_run y confirmación.",
        request=WorkScheduleSetSerializer,
        responses={
            200: ScheduleChangeResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Horarios y Excepciones"],
    )
    def put(self, request: Request, id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        serializer = WorkScheduleSetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de horario semanal inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        entries = serializer.validated_data["entries"]
        confirm = serializer.validated_data.get("confirm", False)
        dry_run = serializer.validated_data.get("dry_run", False)

        result = set_weekly_schedule(
            worker,
            entries,
            actor=request.user,
            confirm=confirm,
            dry_run=dry_run,
        )
        return Response(
            {"applied": result.applied, "impact": result.impact},
            status=status.HTTP_200_OK,
        )


class WorkerExceptionsView(APIView):
    """Add a schedule exception for a worker."""

    permission_classes = [IsWorkerSelfOrStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Crear excepción de horario para trabajador",
        description="Crea una ausencia o turno especial en una fecha revalidando citas afectadas.",
        request=ScheduleExceptionCreateSerializer,
        responses={
            200: ScheduleChangeResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Horarios y Excepciones"],
    )
    def post(self, request: Request, id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        serializer = ScheduleExceptionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de excepción inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        confirm = serializer.validated_data.pop("confirm", False)
        dry_run = serializer.validated_data.pop("dry_run", False)

        result = add_exception(
            worker,
            serializer.validated_data,
            actor=request.user,
            confirm=confirm,
            dry_run=dry_run,
        )
        return Response(
            {"applied": result.applied, "impact": result.impact},
            status=status.HTTP_200_OK,
        )


class WorkerExceptionDetailView(APIView):
    """Delete a schedule exception for a worker."""

    permission_classes = [IsWorkerSelfOrStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Eliminar excepción de horario",
        description="Elimina una excepción de horario previa revalidando la agenda y reasignando citas si aplica.",
        responses={
            200: ScheduleChangeResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Horarios y Excepciones"],
    )
    def delete(self, request: Request, id: int, exception_id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        exception = ScheduleException.objects.filter(id=exception_id, worker_id=worker.id).first()
        if exception is None:
            return Response(
                {"code": "EXCEPTION_NOT_FOUND", "detail": "La excepción solicitada no existe."},
                status=status.HTTP_404_NOT_FOUND,
            )

        confirm = request.query_params.get("confirm", "false").lower() in ("true", "1")
        dry_run = request.query_params.get("dry_run", "false").lower() in ("true", "1")

        if isinstance(request.data, dict):
            confirm = request.data.get("confirm", confirm)
            dry_run = request.data.get("dry_run", dry_run)

        result = remove_exception(
            exception,
            actor=request.user,
            confirm=confirm,
            dry_run=dry_run,
        )
        return Response(
            {"applied": result.applied, "impact": result.impact},
            status=status.HTTP_200_OK,
        )


class WorkerDetailView(APIView):
    """Update a worker's active status (Staff only)."""

    permission_classes = [IsStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Activar o desactivar trabajador (Staff)",
        description="Cambia el estado 'is_active' de un trabajador revalidando citas afectadas.",
        request=WorkerPatchSerializer,
        responses={
            200: ScheduleChangeResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Personal"],
    )
    def patch(self, request: Request, id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        serializer = WorkerPatchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de actualización inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_active = serializer.validated_data["is_active"]
        confirm = serializer.validated_data.get("confirm", False)
        dry_run = serializer.validated_data.get("dry_run", False)

        result = set_worker_active(
            worker,
            is_active,
            actor=request.user,
            confirm=confirm,
            dry_run=dry_run,
        )
        return Response(
            {"applied": result.applied, "impact": result.impact},
            status=status.HTTP_200_OK,
        )


class DayConfigDateView(APIView):
    """Query or update configuration for a specific date (Staff only)."""

    permission_classes = [IsStaff]
    throttle_classes = [UserRateThrottle]

    def _parse_date(self, date_str: str) -> datetime.date | None:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            return None

    @extend_schema(
        summary="Consultar configuración de una fecha específica (Staff)",
        description="Obtiene el cupo configurado, estado de apertura y métricas del día.",
        responses={
            200: DayConfigSummaryResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Configuración de Días"],
    )
    def get(self, request: Request, date: str, *args, **kwargs) -> Response:
        target_date = self._parse_date(date)
        if target_date is None:
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Formato de fecha inválido. Utilice el formato YYYY-MM-DD.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = get_day_config_summary(target_date)
        serializer = DayConfigSummaryResponseSerializer(summary)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Actualizar configuración de una fecha específica (Staff)",
        description="Sobrescribe cupo máximo o estado de apertura de una fecha específica.",
        request=DayConfigUpdateSerializer,
        responses={
            200: DayConfigSummaryResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Configuración de Días"],
    )
    def put(self, request: Request, date: str, *args, **kwargs) -> Response:
        target_date = self._parse_date(date)
        if target_date is None:
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Formato de fecha inválido. Utilice el formato YYYY-MM-DD.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DayConfigUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de configuración inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_appointments = serializer.validated_data.get("max_appointments")
        is_open = serializer.validated_data["is_open"]
        note = serializer.validated_data.get("note", "")

        DayConfig.objects.update_or_create(
            date=target_date,
            defaults={
                "weekday": None,
                "max_appointments": max_appointments,
                "is_open": is_open,
                "note": note,
            },
        )
        schedule_waitlist_processing()

        summary = get_day_config_summary(target_date)
        response_data = DayConfigSummaryResponseSerializer(summary).data
        if not is_open:
            active_count = len(list_active_appointments(target_date))
            response_data["active_appointments_on_closed_day"] = active_count

        return Response(response_data, status=status.HTTP_200_OK)


class DayConfigWeekdayView(APIView):
    """Query or update default weekday configuration (Staff only)."""

    permission_classes = [IsStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Consultar configuración por defecto de día de la semana (Staff)",
        description="Obtiene la configuración semanal por defecto para un día (0=Lunes, 6=Domingo).",
        responses={
            200: DayConfigDetailSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Configuración de Días"],
    )
    def get(self, request: Request, weekday: int, *args, **kwargs) -> Response:
        if weekday < 0 or weekday > 6:
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "El día de la semana debe ser entre 0 y 6.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        day_config = DayConfig.objects.filter(weekday=weekday, date__isnull=True).first()
        if day_config is None:
            day_config = DayConfig(
                weekday=weekday,
                date=None,
                max_appointments=None,
                is_open=True,
                note="",
            )

        serializer = DayConfigDetailSerializer(day_config)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Actualizar configuración por defecto de día de la semana (Staff)",
        description="Actualiza el cupo o estado de apertura semanal por defecto para un día (0=Lunes, 6=Domingo).",
        request=DayConfigUpdateSerializer,
        responses={
            200: DayConfigDetailSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Configuración de Días"],
    )
    def put(self, request: Request, weekday: int, *args, **kwargs) -> Response:
        if weekday < 0 or weekday > 6:
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "El día de la semana debe ser entre 0 y 6.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DayConfigUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de configuración inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_appointments = serializer.validated_data.get("max_appointments")
        is_open = serializer.validated_data["is_open"]
        note = serializer.validated_data.get("note", "")

        day_config, _ = DayConfig.objects.update_or_create(
            weekday=weekday,
            date=None,
            defaults={
                "max_appointments": max_appointments,
                "is_open": is_open,
                "note": note,
            },
        )
        schedule_waitlist_processing()

        serializer = DayConfigDetailSerializer(day_config)
        return Response(serializer.data, status=status.HTTP_200_OK)
