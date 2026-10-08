"""API view for checking service availability and slots."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    AvailabilityQuerySerializer,
    DayAvailabilitySerializer,
)
from agenda.api.throttling import AvailabilityRateThrottle
from agenda.exceptions import ServiceNotFound
from agenda.models import Service
from agenda.selectors import get_day_availability


class AvailabilityView(APIView):
    """Query available appointment slots and daily capacity for a service on a given date."""

    permission_classes = [AllowAny]
    throttle_classes = [AvailabilityRateThrottle]

    @extend_schema(
        summary="Consultar disponibilidad y cupos de un día",
        description=(
            "Calcula los intervalos horarios libres y el cupo restante "
            "para un servicio en una fecha."
        ),
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
