"""Serializers for DayConfig models and summaries."""

from rest_framework import serializers

from agenda.models import DayConfig


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
