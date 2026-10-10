"""API views for managing DayConfig settings and metrics."""

import datetime

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agenda.api.permissions import IsStaff
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.serializers import (
    DayConfigDetailSerializer,
    DayConfigSummaryResponseSerializer,
    DayConfigUpdateSerializer,
)
from agenda.api.throttling import UserRateThrottle
from agenda.models import DayConfig
from agenda.selectors import get_day_config_summary, list_active_appointments
from agenda.services import schedule_waitlist_processing


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
                "booking_min_advance_hours": serializer.validated_data.get(
                    "booking_min_advance_hours"
                ),
                "booking_max_advance_days": serializer.validated_data.get(
                    "booking_max_advance_days"
                ),
                "cancel_min_hours": serializer.validated_data.get("cancel_min_hours"),
                "max_reschedules_per_appointment": serializer.validated_data.get(
                    "max_reschedules_per_appointment"
                ),
                "max_active_per_requester_per_day": serializer.validated_data.get(
                    "max_active_per_requester_per_day"
                ),
                "waitlist_max_per_day": serializer.validated_data.get("waitlist_max_per_day"),
                "default_slot_step_minutes": serializer.validated_data.get(
                    "default_slot_step_minutes"
                ),
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
        description=(
            "Obtiene la configuración semanal por defecto para un día (0=Lunes, 6=Domingo)."
        ),
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
        description=(
            "Actualiza el cupo o estado de apertura semanal por defecto "
            "para un día (0=Lunes, 6=Domingo)."
        ),
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
                "booking_min_advance_hours": serializer.validated_data.get(
                    "booking_min_advance_hours"
                ),
                "booking_max_advance_days": serializer.validated_data.get(
                    "booking_max_advance_days"
                ),
                "cancel_min_hours": serializer.validated_data.get("cancel_min_hours"),
                "max_reschedules_per_appointment": serializer.validated_data.get(
                    "max_reschedules_per_appointment"
                ),
                "max_active_per_requester_per_day": serializer.validated_data.get(
                    "max_active_per_requester_per_day"
                ),
                "waitlist_max_per_day": serializer.validated_data.get("waitlist_max_per_day"),
                "default_slot_step_minutes": serializer.validated_data.get(
                    "default_slot_step_minutes"
                ),
            },
        )
        schedule_waitlist_processing()

        serializer = DayConfigDetailSerializer(day_config)
        return Response(serializer.data, status=status.HTTP_200_OK)
