"""Serializers for agenda API endpoints."""

from rest_framework import serializers


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
    """Serializer for service summary in availability response."""

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
