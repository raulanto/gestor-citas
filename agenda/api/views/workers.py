"""API views for managing worker profiles."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.permissions import IsStaff
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    ScheduleChangeResponseSerializer,
    WorkerPatchSerializer,
)
from agenda.api.throttling import UserRateThrottle
from agenda.exceptions import WorkerNotFound
from agenda.models import Worker
from agenda.services import set_worker_active


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
