"""API views for agenda microapp."""

import datetime
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
    DayConfigDetailSerializer,
    DayConfigSummaryResponseSerializer,
    DayConfigUpdateSerializer,
    ScheduleExceptionCreateSerializer,
    WaitlistEntrySerializer,
    WaitlistQuerySerializer,
    WorkerPatchSerializer,
    WorkerScheduleDetailSerializer,
    WorkScheduleSetSerializer,
)
from agenda.exceptions import ServiceNotFound, WorkerNotFound
from agenda.models import DayConfig, ScheduleException, Service, Worker
from agenda.selectors import (
    get_appointment,
    get_day_availability,
    get_day_config_summary,
    get_worker_schedule,
    list_active_appointments,
    list_appointments_queryset,
    list_unserviceable_waitlist,
    list_waitlist,
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
    schedule_waitlist_processing,
    set_weekly_schedule,
    set_worker_active,
)


def _check_worker_permission(request: Request, worker: Worker) -> Response | None:
    """Validate that the requesting user has permission to view or manage the given worker."""
    if not request.user or not request.user.is_authenticated:
        return Response(
            {"code": "AUTHENTICATION_REQUIRED", "detail": "Se requiere autenticación."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if request.user.is_staff:
        return None
    if hasattr(request.user, "worker_profile") and request.user.worker_profile.id == worker.id:
        return None
    return Response(
        {
            "code": "PERMISSION_DENIED",
            "detail": "No tiene permisos para consultar o modificar este trabajador.",
        },
        status=status.HTTP_403_FORBIDDEN,
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
        unserviceable = query_serializer.validated_data.get("unserviceable", False)

        if unserviceable:
            appts = list_unserviceable_waitlist(from_date=target_date)
            paginator = PageNumberPagination()
            page = paginator.paginate_queryset(appts, request)
            serializer = AppointmentDetailSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

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


# ---------------------------------------------------------------------------
# Phase 6 Schedule Management API Views
# ---------------------------------------------------------------------------


class WorkerScheduleView(APIView):
    """View and replace a worker's weekly work schedule."""

    authentication_classes = [SessionAuthentication, BasicAuthentication]

    def get(self, request: Request, id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        perm_err = _check_worker_permission(request, worker)
        if perm_err is not None:
            return perm_err

        schedule_data = get_worker_schedule(worker)
        serializer = WorkerScheduleDetailSerializer(schedule_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request: Request, id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        perm_err = _check_worker_permission(request, worker)
        if perm_err is not None:
            return perm_err

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

    authentication_classes = [SessionAuthentication, BasicAuthentication]

    def post(self, request: Request, id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        perm_err = _check_worker_permission(request, worker)
        if perm_err is not None:
            return perm_err

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

    authentication_classes = [SessionAuthentication, BasicAuthentication]

    def delete(self, request: Request, id: int, exception_id: int, *args, **kwargs) -> Response:
        worker = Worker.objects.filter(id=id).first()
        if worker is None:
            raise WorkerNotFound()

        perm_err = _check_worker_permission(request, worker)
        if perm_err is not None:
            return perm_err

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

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

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

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def _parse_date(self, date_str: str) -> datetime.date:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            return None

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

    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request: Request, weekday: int, *args, **kwargs) -> Response:
        if weekday < 0 or weekday > 6:
            return Response(
                {"code": "INVALID_PARAMETERS", "detail": "El día de la semana debe ser entre 0 y 6."},
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

    def put(self, request: Request, weekday: int, *args, **kwargs) -> Response:
        if weekday < 0 or weekday > 6:
            return Response(
                {"code": "INVALID_PARAMETERS", "detail": "El día de la semana debe ser entre 0 y 6."},
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
