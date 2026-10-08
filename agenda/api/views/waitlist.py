"""API view for inspecting waitlisted appointments in FIFO order."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.pagination import StandardLimitOffsetPagination
from agenda.api.permissions import IsStaff
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    WaitlistEntrySerializer,
    WaitlistQuerySerializer,
)
from agenda.api.throttling import UserRateThrottle
from agenda.selectors import list_waitlist


class WaitlistView(APIView):
    """List waitlisted appointments for a specific date in FIFO order (Staff only)."""

    permission_classes = [IsStaff]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Listar lista de espera FIFO del día (Staff)",
        description=(
            "Consulta las citas en estado WAITLISTED de una fecha "
            "en orden FIFO con posición absoluta."
        ),
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
