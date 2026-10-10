"""DayConfig model representing daily capacity quota and open/closed status."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from agenda.models.enums import Weekday


class DayConfig(models.Model):
    """Daily configuration for appointment quota and open/closed status.

    Can be defined as a general weekday default or as a specific single-date override.
    """

    weekday = models.PositiveSmallIntegerField(
        "día de la semana (default)",
        choices=Weekday.choices,
        null=True,
        blank=True,
    )
    date = models.DateField(
        "fecha específica (override)",
        null=True,
        blank=True,
    )
    max_appointments = models.PositiveIntegerField(
        "cupo máximo de citas",
        null=True,
        blank=True,
        help_text=(
            "Dejar vacío para usar únicamente la capacidad calculada del personal. 0 es válido."
        ),
    )
    is_open = models.BooleanField(
        "abierto para citas",
        default=True,
    )
    note = models.CharField(
        "nota / descripción",
        max_length=255,
        blank=True,
        default="",
    )
    booking_min_advance_hours = models.PositiveIntegerField(
        "anticipación mínima para agendar (horas)",
        null=True,
        blank=True,
        help_text="Horas de anticipación mínima. Vacío para heredar del sistema.",
    )
    booking_max_advance_days = models.PositiveIntegerField(
        "ventana máxima a futuro (días)",
        null=True,
        blank=True,
        help_text="Días máximos a futuro para reservar. Vacío para heredar del sistema.",
    )
    cancel_min_hours = models.PositiveIntegerField(
        "anticipación mínima para cancelar (horas)",
        null=True,
        blank=True,
        help_text="Horas de anticipación mínima para cancelar. Vacío para heredar del sistema.",
    )
    max_reschedules_per_appointment = models.PositiveIntegerField(
        "máximo de reprogramaciones por cita",
        null=True,
        blank=True,
        help_text="Reprogramaciones permitidas por cita. Vacío para heredar del sistema.",
    )
    max_active_per_requester_per_day = models.PositiveIntegerField(
        "máximo de citas activas por solicitante/día",
        null=True,
        blank=True,
        help_text="Citas activas por solicitante en esta fecha. Vacío para heredar del sistema.",
    )
    waitlist_max_per_day = models.PositiveIntegerField(
        "tope de lista de espera por día",
        null=True,
        blank=True,
        help_text="Capacidad máxima de la lista de espera. Vacío para heredar del sistema.",
    )
    default_slot_step_minutes = models.PositiveIntegerField(
        "granularidad de horarios (minutos)",
        null=True,
        blank=True,
        help_text="Paso de cuadrícula en minutos (ej. 15). Vacío para heredar del sistema.",
    )

    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        verbose_name = "configuración de día"
        verbose_name_plural = "configuraciones de días"
        ordering = ["date", "weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["weekday"],
                condition=Q(weekday__isnull=False),
                name="unique_day_config_weekday",
            ),
            models.UniqueConstraint(
                fields=["date"],
                condition=Q(date__isnull=False),
                name="unique_day_config_date",
            ),
            models.CheckConstraint(
                condition=(
                    (Q(weekday__isnull=False) & Q(date__isnull=True))
                    | (Q(weekday__isnull=True) & Q(date__isnull=False))
                ),
                name="day_config_either_weekday_or_date",
            ),
        ]

    def __str__(self) -> str:
        if self.date is not None:
            scope = f"Fecha {self.date}"
        elif self.weekday is not None:
            scope = f"Día {self.get_weekday_display()}"
        else:
            scope = "Sin alcance"

        status_str = "Abierto" if self.is_open else "Cerrado"
        if self.max_appointments is not None:
            quota_str = f"Cupo: {self.max_appointments}"
        else:
            quota_str = "Sin tope propio"
        return f"{scope} - {status_str} ({quota_str})"

    def clean(self) -> None:
        super().clean()
        has_weekday = self.weekday is not None
        has_date = self.date is not None

        if has_weekday == has_date:
            raise ValidationError(
                "Debe especificar exactamente un día de la semana (default) "
                "o una fecha (override), no ambos ni ninguno."
            )
