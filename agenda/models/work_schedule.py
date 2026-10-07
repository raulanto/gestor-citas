"""WorkSchedule model representing a worker's regular weekly schedule."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from agenda.models.enums import Weekday


class WorkSchedule(models.Model):
    """Weekly working schedule for a staff member on a specific weekday."""

    worker = models.ForeignKey(
        "agenda.Worker",
        on_delete=models.CASCADE,
        related_name="schedules",
        verbose_name="trabajador",
    )
    weekday = models.PositiveSmallIntegerField(
        "día de la semana",
        choices=Weekday.choices,
    )
    start_time = models.TimeField("hora de entrada")
    end_time = models.TimeField("hora de salida")
    break_start = models.TimeField("inicio de descanso", null=True, blank=True)
    break_end = models.TimeField("fin de descanso", null=True, blank=True)

    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        verbose_name = "horario laboral"
        verbose_name_plural = "horarios laborales"
        ordering = ["worker", "weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["worker", "weekday"],
                name="unique_worker_weekday_schedule",
            ),
            models.CheckConstraint(
                condition=Q(start_time__lt=F("end_time")),
                name="work_schedule_start_lt_end",
            ),
            models.CheckConstraint(
                condition=(
                    (Q(break_start__isnull=True) & Q(break_end__isnull=True))
                    | (Q(break_start__isnull=False) & Q(break_end__isnull=False))
                ),
                name="work_schedule_break_all_or_nothing",
            ),
            models.CheckConstraint(
                condition=Q(break_start__isnull=True)
                | (
                    Q(break_start__gte=F("start_time"))
                    & Q(break_start__lt=F("break_end"))
                    & Q(break_end__lte=F("end_time"))
                ),
                name="work_schedule_break_within_shift",
            ),
        ]

    def __str__(self) -> str:
        worker_name = getattr(self.worker, "full_name", f"Worker #{self.worker_id}")
        return f"{worker_name} - {self.get_weekday_display()} ({self.start_time} - {self.end_time})"

    def clean(self) -> None:
        super().clean()
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValidationError(
                    {"end_time": "La hora de salida debe ser posterior a la hora de entrada."}
                )

        has_break_start = self.break_start is not None
        has_break_end = self.break_end is not None

        if has_break_start != has_break_end:
            raise ValidationError(
                "El descanso debe tener definidos tanto el inicio como el fin, "
                "o ninguno de los dos."
            )

        if has_break_start and has_break_end:
            if self.break_start >= self.break_end:
                raise ValidationError(
                    {"break_end": "El fin del descanso debe ser posterior al inicio del descanso."}
                )
            if self.start_time and self.break_start < self.start_time:
                raise ValidationError(
                    {
                        "break_start": (
                            "El inicio del descanso no puede ser anterior a la hora de entrada."
                        )
                    }
                )
            if self.end_time and self.break_end > self.end_time:
                raise ValidationError(
                    {"break_end": "El fin del descanso no puede ser posterior a la hora de salida."}
                )
