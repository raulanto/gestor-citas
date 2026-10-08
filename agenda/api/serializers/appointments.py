"""Serializers for appointment creation, details, cancellation, and rescheduling."""

import datetime

from django.conf import settings
from rest_framework import serializers

from agenda.constants import AppointmentStatus
from agenda.models import Appointment
from agenda.selectors.waitlist import waitlist_position

from .availability import ServiceSummarySerializer
from .requesters import (
    RequesterDetailSerializer,
    RequesterInputSerializer,
    RequesterPublicDetailSerializer,
    RequesterWorkerDetailSerializer,
)


class AppointmentCreateSerializer(serializers.Serializer):
    """Input serializer for creating/booking a new appointment."""

    requester = RequesterInputSerializer(required=True)
    service = serializers.IntegerField(
        required=True,
        min_value=1,
        error_messages={
            "required": "El parámetro 'service' es obligatorio.",
            "invalid": "El identificador del servicio debe ser un número entero válido.",
        },
    )
    start_at = serializers.DateTimeField(
        required=True,
        error_messages={
            "required": "La fecha y hora de inicio ('start_at') es obligatoria.",
            "invalid": "Formato de fecha y hora inválido. Utilice formato ISO-8601 aware.",
        },
    )


class AppointmentCancelSerializer(serializers.Serializer):
    """Input serializer for appointment cancellation."""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=500,
    )
    force = serializers.BooleanField(required=False, default=False)


class AppointmentRescheduleSerializer(serializers.Serializer):
    """Input serializer for appointment rescheduling."""

    start_at = serializers.DateTimeField(
        required=True,
        error_messages={
            "required": "La nueva fecha y hora ('start_at') es obligatoria.",
            "invalid": "Formato de fecha y hora inválido. Utilice formato ISO-8601 aware.",
        },
    )
    allow_waitlist = serializers.BooleanField(required=False, default=False)
    force = serializers.BooleanField(required=False, default=False)


class AppointmentListQuerySerializer(serializers.Serializer):
    """Query parameters serializer for listing appointments."""

    date = serializers.DateField(
        required=False,
        allow_null=True,
        error_messages={
            "invalid": "Formato de fecha inválido. Utilice el formato YYYY-MM-DD.",
        },
    )
    status = serializers.CharField(required=False, allow_blank=True, default="")
    unserviceable = serializers.BooleanField(required=False, default=False)


class BaseAppointmentDetailSerializer(serializers.ModelSerializer):
    """Base response serializer for appointment details."""

    service = ServiceSummarySerializer()
    worker_name = serializers.SerializerMethodField()
    waitlist_position = serializers.SerializerMethodField()
    reschedules_remaining = serializers.SerializerMethodField()
    can_cancel_until = serializers.SerializerMethodField()
    rescheduled_from = serializers.UUIDField(source="rescheduled_from_id", allow_null=True)
    rescheduled_to = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "status",
            "service",
            "date",
            "start_at",
            "end_at",
            "worker_name",
            "waitlist_position",
            "reschedule_count",
            "reschedules_remaining",
            "can_cancel_until",
            "rescheduled_from",
            "rescheduled_to",
        ]

    def get_worker_name(self, obj: Appointment) -> str | None:
        if obj.worker is not None:
            return obj.worker.full_name
        return None

    def get_waitlist_position(self, obj: Appointment) -> int | None:
        return waitlist_position(obj)

    def get_reschedules_remaining(self, obj: Appointment) -> int:
        max_reschedules = getattr(settings, "MAX_RESCHEDULES_PER_APPOINTMENT", 2)
        return max(0, max_reschedules - obj.reschedule_count)

    def get_can_cancel_until(self, obj: Appointment) -> str | None:
        if obj.status == AppointmentStatus.CONFIRMED:
            min_hours = getattr(settings, "CANCEL_MIN_HOURS", 4)
            limit = obj.start_at - datetime.timedelta(hours=min_hours)
            return limit.isoformat()
        return None

    def get_rescheduled_to(self, obj: Appointment) -> str | None:
        child = obj.rescheduled_to
        return str(child.id) if child is not None else None


class RequesterAppointmentDetailSerializer(BaseAppointmentDetailSerializer):
    """Appointment detail serializer for requesters with minimal personal data."""

    requester = RequesterPublicDetailSerializer()

    class Meta(BaseAppointmentDetailSerializer.Meta):
        fields = ["requester", *BaseAppointmentDetailSerializer.Meta.fields]


class WorkerAppointmentDetailSerializer(BaseAppointmentDetailSerializer):
    """Appointment detail serializer for assigned workers with requester phone."""

    requester = RequesterWorkerDetailSerializer()

    class Meta(BaseAppointmentDetailSerializer.Meta):
        fields = ["requester", *BaseAppointmentDetailSerializer.Meta.fields]


class StaffAppointmentDetailSerializer(BaseAppointmentDetailSerializer):
    """Full appointment detail serializer for staff with full requester details."""

    requester = RequesterDetailSerializer()

    class Meta(BaseAppointmentDetailSerializer.Meta):
        fields = ["requester", *BaseAppointmentDetailSerializer.Meta.fields]


AppointmentDetailSerializer = StaffAppointmentDetailSerializer


class AppointmentBookingResponseSerializer(BaseAppointmentDetailSerializer):
    """Appointment response serializer for booking and reschedule with one-time manage_token."""

    manage_token = serializers.SerializerMethodField()
    requester = RequesterPublicDetailSerializer()

    class Meta(BaseAppointmentDetailSerializer.Meta):
        fields = [
            "manage_token",
            "requester",
            *BaseAppointmentDetailSerializer.Meta.fields,
        ]

    def get_manage_token(self, obj: Appointment) -> str | None:
        return getattr(obj, "manage_token", None) or self.context.get("manage_token")


class RotateTokenResponseSerializer(serializers.Serializer):
    """Response serializer for rotating an appointment manage token."""

    appointment_id = serializers.UUIDField()
    manage_token = serializers.CharField()
