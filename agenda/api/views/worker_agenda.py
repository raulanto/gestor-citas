"""API view for worker daily confirmed agenda."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.roles import Role, get_user_role
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    WorkerAgendaAppointmentSerializer,
    WorkerAgendaQuerySerializer,
)
from agenda.api.throttling import UserRateThrottle
from agenda.exceptions import WorkerNotFound
from agenda.models import Worker
from agenda.selectors import list_worker_agenda


class WorkerAgendaView(APIView):
    """Retrieve daily confirmed agenda for a worker."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Consultar agenda del trabajador",
        description=(
            "Consulta las citas CONFIRMED del día con datos de contacto del solicitante "
            "para el trabajador."
        ),
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
