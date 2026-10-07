"""AppointmentEvent model for tracking appointment state transitions and audit history."""

from django.conf import settings
from django.db import models

from agenda.constants import AppointmentStatus


class AppointmentEvent(models.Model):
    """Audit log entry for appointment lifecycle state transitions."""

    appointment = models.ForeignKey(
        "agenda.Appointment",
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="cita",
    )
    from_status = models.CharField(
        "estado anterior",
        max_length=20,
        blank=True,
        default="",
    )
    to_status = models.CharField(
        "estado nuevo",
        max_length=20,
        choices=AppointmentStatus.choices,
    )
    worker = models.ForeignKey(
        "agenda.Worker",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="trabajador",
    )
    note = models.TextField("nota", blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="actor",
    )
    created_at = models.DateTimeField("creado el", auto_now_add=True)

    class Meta:
        verbose_name = "evento de cita"
        verbose_name_plural = "eventos de cita"
        ordering = ["created_at"]

    def __str__(self) -> str:
        from_s = self.from_status or "INICIO"
        return f"[{self.created_at}] {self.appointment_id}: {from_s} -> {self.to_status}"
