"""Serializers for agenda API endpoints."""

from rest_framework import serializers

from agenda.models import Appointment


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


class RequesterDetailSerializer(serializers.Serializer):
    """Detail serializer for requester in appointment response."""

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


class AppointmentDetailSerializer(serializers.ModelSerializer):
    """Response serializer for appointment details."""

    service = ServiceSummarySerializer()
    requester = RequesterDetailSerializer()
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
            "requester",
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
        from agenda.selectors.waitlist import waitlist_position

        return waitlist_position(obj)

    def get_reschedules_remaining(self, obj: Appointment) -> int:
        from django.conf import settings

        max_reschedules = getattr(settings, "MAX_RESCHEDULES_PER_APPOINTMENT", 2)
        return max(0, max_reschedules - obj.reschedule_count)

    def get_can_cancel_until(self, obj: Appointment) -> str | None:
        from django.conf import settings

        from agenda.constants import AppointmentStatus

        if obj.status == AppointmentStatus.CONFIRMED:
            import datetime

            min_hours = getattr(settings, "CANCEL_MIN_HOURS", 4)
            limit = obj.start_at - datetime.timedelta(hours=min_hours)
            return limit.isoformat()
        return None

    def get_rescheduled_to(self, obj: Appointment) -> str | None:
        child = obj.rescheduled_to
        return str(child.id) if child is not None else None

