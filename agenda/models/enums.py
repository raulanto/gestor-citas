"""Enumerations for agenda models."""

from django.db import models


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Lunes"
    TUESDAY = 1, "Martes"
    WEDNESDAY = 2, "Miércoles"
    THURSDAY = 3, "Jueves"
    FRIDAY = 4, "Viernes"
    SATURDAY = 5, "Sábado"
    SUNDAY = 6, "Domingo"


class ExceptionKind(models.TextChoices):
    ABSENCE = "ABSENCE", "Ausencia"
    SPECIAL_HOURS = "SPECIAL_HOURS", "Horario especial"


from agenda.constants import AppointmentStatus  # noqa: E402

__all__ = ["AppointmentStatus", "ExceptionKind", "Weekday"]
