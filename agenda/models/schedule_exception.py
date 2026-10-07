"""ScheduleException model representing single-date absences or special hours for a worker."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from agenda.models.enums import ExceptionKind


class ScheduleException(models.Model):
    """Exception to standard weekly schedule for a specific date (absence or special hours)."""

    worker = models.ForeignKey(
        "agenda.Worker",
        on_delete=models.CASCADE,
        related_name="schedule_exceptions",
        verbose_name="trabajador",
    )
    date = models.DateField("fecha")
    kind = models.CharField(
        "tipo de excepción",
        max_length=20,
        choices=ExceptionKind.choices,
    )
    start_time = models.TimeField("hora de entrada", null=True, blank=True)
    end_time = models.TimeField("hora de salida", null=True, blank=True)
    break_start = models.TimeField("inicio de descanso", null=True, blank=True)
    break_end = models.TimeField("fin de descanso", null=True, blank=True)
    reason = models.CharField("motivo", max_length=255, blank=True, default="")

    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        verbose_name = "excepción de horario"
        verbose_name_plural = "excepciones de horario"
        ordering = ["worker", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["worker", "date"],
                name="unique_worker_date_exception",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind=ExceptionKind.ABSENCE,
                        start_time__isnull=True,
                        end_time__isnull=True,
                        break_start__isnull=True,
                        break_end__isnull=True,
                    )
                    | (
                        Q(
                            kind=ExceptionKind.SPECIAL_HOURS,
                            start_time__isnull=False,
                            end_time__isnull=False,
                            start_time__lt=F("end_time"),
                        )
                        & (
                            (Q(break_start__isnull=True) & Q(break_end__isnull=True))
                            | (
                                Q(break_start__isnull=False)
                                & Q(break_end__isnull=False)
                                & Q(break_start__gte=F("start_time"))
                                & Q(break_start__lt=F("break_end"))
                                & Q(break_end__lte=F("end_time"))
                            )
                        )
                    )
                ),
                name="schedule_exception_valid_structure",
            ),
        ]

    def __str__(self) -> str:
        worker_name = getattr(self.worker, "full_name", f"Worker #{self.worker_id}")
        return f"{worker_name} - {self.date} ({self.get_kind_display()})"

    def clean(self) -> None:
        super().clean()
        if self.kind == ExceptionKind.ABSENCE:
            if (
                self.start_time is not None
                or self.end_time is not None
                or self.break_start is not None
                or self.break_end is not None
            ):
                raise ValidationError(
                    "Una excepción de ausencia (ABSENCE) no debe tener horas "
                    "de entrada, salida ni descansos."
                )
        elif self.kind == ExceptionKind.SPECIAL_HOURS:
            if self.start_time is None or self.end_time is None:
                raise ValidationError(
                    "Un horario especial (SPECIAL_HOURS) requiere definir "
                    "tanto la hora de entrada como la de salida."
                )
            if self.start_time >= self.end_time:
                raise ValidationError(
                    {"end_time": "La hora de salida debe ser posterior a la hora de entrada."}
                )

            has_break_start = self.break_start is not None
            has_break_end = self.break_end is not None

            if has_break_start != has_break_end:
                raise ValidationError(
                    "El descanso debe tener definidos tanto el inicio "
                    "como el fin, o ninguno de los dos."
                )

            if has_break_start and has_break_end:
                if self.break_start >= self.break_end:
                    raise ValidationError(
                        {
                            "break_end": (
                                "El fin del descanso debe ser posterior al inicio del descanso."
                            )
                        }
                    )
                if self.break_start < self.start_time:
                    raise ValidationError(
                        {
                            "break_start": (
                                "El inicio del descanso no puede ser anterior a la hora de entrada."
                            )
                        }
                    )
                if self.break_end > self.end_time:
                    raise ValidationError(
                        {
                            "break_end": (
                                "El fin del descanso no puede ser posterior a la hora de salida."
                            )
                        }
                    )
