"""Serializers for worker schedules and exceptions."""

from rest_framework import serializers

from agenda.models import (
    ExceptionKind,
    ScheduleException,
    Worker,
    WorkSchedule,
)


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


class ScheduleChangeResponseSerializer(serializers.Serializer):
    """Response serializer for worker schedule changes impact."""

    applied = serializers.BooleanField(
        help_text="Indica si los cambios fueron aplicados en la base de datos."
    )
    impact = serializers.DictField(help_text="Desglose del impacto sobre citas existentes.")
