"""Serializers for waitlist queries and entries."""

from rest_framework import serializers

from .availability import ServiceSummarySerializer


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
