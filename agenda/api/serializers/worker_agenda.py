"""Serializers for worker daily agenda."""

from rest_framework import serializers

from agenda.models import Appointment

from .availability import ServiceSummarySerializer
from .requesters import RequesterWorkerDetailSerializer


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
