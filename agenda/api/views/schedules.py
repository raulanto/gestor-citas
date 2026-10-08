"""API views for managing worker weekly schedules and date exceptions."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.permissions import IsWorkerSelfOrStaff
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    ScheduleChangeResponseSerializer,
    ScheduleExceptionCreateSerializer,
    WorkerScheduleDetailSerializer,
    WorkScheduleSetSerializer,
)
from agenda.api.throttling import UserRateThrottle
from agenda.exceptions import WorkerNotFound
from agenda.models import ScheduleException, Worker
from agenda.selectors import get_worker_schedule
from agenda.services import (
    add_exception,
    remove_exception,
    set_weekly_schedule,
)


class WorkerScheduleView(APIView):
    """View and replace a worker's weekly work schedule."""

    permission_classes = [IsWorkerSelfOrStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Consultar horario semanal de trabajador",
        description=(
            "Consulta los turnos y descansos semanales de un trabajador "
            "junto a sus excepciones futuras."
        ),
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
        description=(
            "Reemplaza el horario semanal revalidando citas futuras y "
            "admitiendo dry_run y confirmación."
        ),
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
        description=(
            "Elimina una excepción de horario previa revalidando la agenda "
            "y reasignando citas si aplica."
        ),
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
