"""Serializers for agenda API endpoints."""

import datetime

from django.conf import settings
from rest_framework import serializers

from agenda.constants import AppointmentStatus
from agenda.models import (
    Appointment,
    DayConfig,
    ExceptionKind,
    ScheduleException,
    Worker,
    WorkSchedule,
)
from agenda.selectors.waitlist import waitlist_position


class AvailabilityQuerySerializer(serializers.Serializer):
    """Query parameters serializer for availability endpoint."""

    date = serializers.DateField(
        required=True,
        error_messages={
            "required": "El parámetro 'date' es obligatorio.",
            "invalid": "Formato de fecha inválido. Utilice el formato YYYY-MM-DD.",
        },
    )
    service = serializers.IntegerField(
        required=True,
        min_value=1,
        error_messages={
            "required": "El parámetro 'service' es obligatorio.",
            "invalid": "El parámetro 'service' debe ser un identificador numérico válido.",
        },
    )


class ServiceSummarySerializer(serializers.Serializer):
    """Serializer for service summary."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    duration_minutes = serializers.IntegerField()


class SlotSerializer(serializers.Serializer):
    """Serializer for an available appointment slot."""

    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    free_workers = serializers.IntegerField()


class DayAvailabilitySerializer(serializers.Serializer):
    """Response serializer for day availability."""

    date = serializers.DateField()
    service = ServiceSummarySerializer()
    is_open = serializers.BooleanField()
    reason = serializers.CharField(allow_null=True)
    effective_quota = serializers.IntegerField()
    remaining_quota = serializers.IntegerField()
    slots = SlotSerializer(many=True)


class RequesterInputSerializer(serializers.Serializer):
    """Input serializer for requester contact details in appointment booking."""

    full_name = serializers.CharField(
        max_length=150,
        required=True,
        error_messages={"required": "El nombre completo del solicitante es obligatorio."},
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs: dict) -> dict:
        phone = (attrs.get("phone") or "").strip()
        email = (attrs.get("email") or "").strip()
        if not phone and not email:
            raise serializers.ValidationError(
                "Debe proporcionar al menos un teléfono o un correo electrónico."
            )
        return attrs


class RequesterPublicDetailSerializer(serializers.Serializer):
    """Public requester serializer with minimal personal data (no phone, no email)."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()


class RequesterWorkerDetailSerializer(serializers.Serializer):
    """Worker requester serializer with contact phone for appointment fulfillment (no email)."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    phone = serializers.CharField()


class RequesterDetailSerializer(serializers.Serializer):
    """Staff full requester detail serializer with all contact information."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.EmailField()


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


class WaitlistQuerySerializer(serializers.Serializer):
    """Query parameters serializer for waitlist endpoint."""

    date = serializers.DateField(
        required=True,
        error_messages={
            "required": "El parámetro 'date' es obligatorio.",
            "invalid": "Formato de fecha inválido. Utilice el formato YYYY-MM-DD.",
        },
    )


class WaitlistEntrySerializer(serializers.Serializer):
    """Serializer for waitlist entry in list response."""

    id = serializers.UUIDField(source="appointment.id")
    position = serializers.IntegerField()
    requester_name = serializers.CharField(source="appointment.requester.full_name")
    service = ServiceSummarySerializer(source="appointment.service")
    start_at = serializers.DateTimeField(source="appointment.start_at")
    created_at = serializers.DateTimeField(source="appointment.created_at")


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


# Default / backward-compatible alias for staff appointment detail
AppointmentDetailSerializer = StaffAppointmentDetailSerializer


class AppointmentBookingResponseSerializer(BaseAppointmentDetailSerializer):
    """Appointment response serializer for booking and reschedule with one-time manage_token."""

    manage_token = serializers.CharField()
    requester = RequesterPublicDetailSerializer()

    class Meta(BaseAppointmentDetailSerializer.Meta):
        fields = [
            "manage_token",
            "requester",
            *BaseAppointmentDetailSerializer.Meta.fields,
        ]


class WorkerAgendaAppointmentSerializer(serializers.ModelSerializer):
    """Serializer for appointments in a worker's daily agenda."""

    service = ServiceSummarySerializer()
    requester = RequesterWorkerDetailSerializer()

    class Meta:
        model = Appointment
        fields = ["id", "service", "start_at", "end_at", "requester"]


class WorkerAgendaQuerySerializer(serializers.Serializer):
    """Query parameters serializer for me/agenda endpoint."""

    date = serializers.DateField(
        required=True,
        error_messages={
            "required": "El parámetro 'date' es obligatorio.",
            "invalid": "Formato de fecha inválido. Utilice el formato YYYY-MM-DD.",
        },
    )
    worker_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        error_messages={
            "invalid": "El parámetro 'worker_id' debe ser un identificador numérico.",
        },
    )


class RotateTokenResponseSerializer(serializers.Serializer):
    """Response serializer for rotating an appointment manage token."""

    appointment_id = serializers.UUIDField()
    manage_token = serializers.CharField()


# ---------------------------------------------------------------------------
# Phase 6 Schedule Management Serializers
# ---------------------------------------------------------------------------


class WorkScheduleEntrySerializer(serializers.Serializer):
    """Serializer for an individual weekly schedule entry."""

    weekday = serializers.IntegerField(
        min_value=0,
        max_value=6,
        required=True,
        error_messages={
            "required": "El campo 'weekday' es obligatorio.",
            "min_value": "El día de la semana debe ser entre 0 (Lunes) y 6 (Domingo).",
            "max_value": "El día de la semana debe ser entre 0 (Lunes) y 6 (Domingo).",
        },
    )
    start_time = serializers.TimeField(
        required=True,
        error_messages={"required": "La hora de inicio ('start_time') es obligatoria."},
    )
    end_time = serializers.TimeField(
        required=True,
        error_messages={"required": "La hora de fin ('end_time') es obligatoria."},
    )
    break_start = serializers.TimeField(required=False, allow_null=True, default=None)
    break_end = serializers.TimeField(required=False, allow_null=True, default=None)

    def validate(self, attrs: dict) -> dict:
        start = attrs.get("start_time")
        end = attrs.get("end_time")
        b_start = attrs.get("break_start")
        b_end = attrs.get("break_end")

        if start and end and end <= start:
            raise serializers.ValidationError(
                "La hora de fin debe ser posterior a la hora de inicio."
            )

        if (b_start and not b_end) or (b_end and not b_start):
            raise serializers.ValidationError(
                "Ambos break_start y break_end deben ser definidos o ambos nulos."
            )

        if b_start and b_end:
            if b_end <= b_start:
                raise serializers.ValidationError(
                    "El fin del descanso debe ser posterior al inicio del descanso."
                )
            if b_start <= start or b_end >= end:
                raise serializers.ValidationError(
                    "El descanso debe estar estrictamente dentro del turno de trabajo."
                )

        return attrs


class WorkScheduleSetSerializer(serializers.Serializer):
    """Input serializer for replacing a worker's full weekly work schedule."""

    entries = WorkScheduleEntrySerializer(many=True, required=True)
    confirm = serializers.BooleanField(required=False, default=False)
    dry_run = serializers.BooleanField(required=False, default=False)

    def validate_entries(self, entries: list[dict]) -> list[dict]:
        weekdays = [e["weekday"] for e in entries]
        if len(weekdays) != len(set(weekdays)):
            raise serializers.ValidationError(
                "No puede haber más de una entrada por día de la semana."
            )
        return entries


class ScheduleExceptionCreateSerializer(serializers.Serializer):
    """Input serializer for creating a schedule exception."""

    date = serializers.DateField(
        required=True,
        error_messages={"required": "La fecha ('date') es obligatoria."},
    )
    kind = serializers.ChoiceField(
        choices=ExceptionKind.choices,
        required=True,
        error_messages={"required": "El tipo de excepción ('kind') es obligatorio."},
    )
    start_time = serializers.TimeField(required=False, allow_null=True, default=None)
    end_time = serializers.TimeField(required=False, allow_null=True, default=None)
    break_start = serializers.TimeField(required=False, allow_null=True, default=None)
    break_end = serializers.TimeField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    confirm = serializers.BooleanField(required=False, default=False)
    dry_run = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict) -> dict:
        kind = attrs.get("kind")
        start = attrs.get("start_time")
        end = attrs.get("end_time")
        b_start = attrs.get("break_start")
        b_end = attrs.get("break_end")

        if kind == ExceptionKind.SPECIAL_HOURS:
            if not start or not end:
                raise serializers.ValidationError(
                    "start_time y end_time son obligatorios para horarios especiales."
                )
            if end <= start:
                raise serializers.ValidationError(
                    "La hora de fin debe ser posterior a la hora de inicio."
                )
            if (b_start and not b_end) or (b_end and not b_start):
                raise serializers.ValidationError(
                    "Ambos break_start y break_end deben ser definidos o ambos nulos."
                )
            if b_start and b_end:
                if b_end <= b_start:
                    raise serializers.ValidationError(
                        "El fin del descanso debe ser posterior al inicio del descanso."
                    )
                if b_start <= start or b_end >= end:
                    raise serializers.ValidationError(
                        "El descanso debe estar estrictamente dentro del turno."
                    )
        return attrs


class WorkerPatchSerializer(serializers.Serializer):
    """Input serializer for updating a worker's active status."""

    is_active = serializers.BooleanField(required=True)
    confirm = serializers.BooleanField(required=False, default=False)
    dry_run = serializers.BooleanField(required=False, default=False)


class WorkScheduleDetailSerializer(serializers.ModelSerializer):
    """Detail serializer for WorkSchedule."""

    class Meta:
        model = WorkSchedule
        fields = ["id", "weekday", "start_time", "end_time", "break_start", "break_end"]


class ScheduleExceptionDetailSerializer(serializers.ModelSerializer):
    """Detail serializer for ScheduleException."""

    class Meta:
        model = ScheduleException
        fields = [
            "id",
            "date",
            "kind",
            "start_time",
            "end_time",
            "break_start",
            "break_end",
            "reason",
        ]


class WorkerScheduleDetailSerializer(serializers.Serializer):
    """Response serializer for worker schedule including weekly entries and exceptions."""

    worker = serializers.SerializerMethodField()
    weekly_schedules = WorkScheduleDetailSerializer(many=True)
    exceptions = ScheduleExceptionDetailSerializer(many=True)

    def get_worker(self, obj: dict) -> dict:
        worker: Worker = obj["worker"]
        return {
            "id": worker.id,
            "full_name": worker.full_name,
            "is_active": worker.is_active,
        }


class DayConfigUpdateSerializer(serializers.Serializer):
    """Input serializer for updating DayConfig date or weekday defaults."""

    max_appointments = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, default=None
    )
    is_open = serializers.BooleanField(required=True)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class DayConfigDetailSerializer(serializers.ModelSerializer):
    """Serializer for DayConfig model."""

    class Meta:
        model = DayConfig
        fields = ["id", "weekday", "date", "max_appointments", "is_open", "note", "updated_at"]


class DayConfigSummaryResponseSerializer(serializers.Serializer):
    """Response serializer for DayConfig and capacity metrics summary."""

    date = serializers.DateField()
    day_config = DayConfigDetailSerializer()
    is_open = serializers.BooleanField()
    effective_quota = serializers.IntegerField(allow_null=True)
    quota_consumed = serializers.IntegerField()
    active_count = serializers.IntegerField()
    is_over_quota = serializers.BooleanField()
    active_appointments_on_closed_day = serializers.IntegerField(required=False, default=0)
