"""Service model representing appointment types and durations."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from agenda.constants import MAX_SERVICE_DURATION_MINUTES, MIN_SERVICE_DURATION_MINUTES


class Service(models.Model):
    """Type of appointment service offered, with configurable duration in minutes."""

    name = models.CharField("nombre", max_length=100, unique=True)
    description = models.TextField("descripción", blank=True, default="")
    duration_minutes = models.PositiveSmallIntegerField("duración en minutos")
    is_active = models.BooleanField("activo", default=True)

    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        verbose_name = "servicio"
        verbose_name_plural = "servicios"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(duration_minutes__gte=MIN_SERVICE_DURATION_MINUTES)
                & Q(duration_minutes__lte=MAX_SERVICE_DURATION_MINUTES),
                name="service_duration_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.duration_minutes} min)"

    def clean(self) -> None:
        super().clean()
        if self.duration_minutes is not None and not (
            MIN_SERVICE_DURATION_MINUTES <= self.duration_minutes <= MAX_SERVICE_DURATION_MINUTES
        ):
            raise ValidationError(
                {
                    "duration_minutes": (
                        f"La duración debe ser entre {MIN_SERVICE_DURATION_MINUTES} y "
                        f"{MAX_SERVICE_DURATION_MINUTES} minutos."
                    )
                }
            )
