"""Appointment model for booking management."""

import uuid

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Func, Q

from agenda.constants import OCCUPYING_STATUSES, AppointmentStatus


class TsTzRange(Func):
    """PostgreSQL tstzrange function expression."""

    function = "tstzrange"
    output_field = DateTimeRangeField()


class PostgresExclusionConstraint(ExclusionConstraint):
    """Exclusion constraint that applies on PostgreSQL and is safely ignored on other backends."""

    def constraint_sql(self, model, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return None
        return super().constraint_sql(model, schema_editor)

    def create_sql(self, model, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return None
        return super().create_sql(model, schema_editor)

    def remove_sql(self, model, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return None
        return super().remove_sql(model, schema_editor)


class Appointment(models.Model):
    """Appointment entity with worker assignment, requester, and schedule details."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        "agenda.Requester",
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="solicitante",
    )
    service = models.ForeignKey(
        "agenda.Service",
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="servicio",
    )
    worker = models.ForeignKey(
        "agenda.Worker",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="trabajador",
    )
    date = models.DateField("fecha", db_index=True)
    start_at = models.DateTimeField("inicio")
    end_at = models.DateTimeField("fin")
    status = models.CharField(
        "estado",
        max_length=20,
        choices=AppointmentStatus.choices,
    )
    reschedule_count = models.PositiveSmallIntegerField(
        "número de reprogramaciones",
        default=0,
    )
    rescheduled_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rescheduled_children",
        verbose_name="reprogramada desde",
    )

    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        verbose_name = "cita"
        verbose_name_plural = "citas"
        ordering = ["-start_at"]
        indexes = [
            models.Index(fields=["date", "status"], name="appointment_date_status_idx"),
            models.Index(fields=["worker", "date"], name="appointment_worker_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")),
                name="appointment_end_gt_start",
            ),
            models.CheckConstraint(
                condition=~Q(status=AppointmentStatus.CONFIRMED) | Q(worker__isnull=False),
                name="appointment_confirmed_has_worker",
            ),
            models.CheckConstraint(
                condition=~Q(status=AppointmentStatus.WAITLISTED) | Q(worker__isnull=True),
                name="appointment_waitlisted_no_worker",
            ),
            models.CheckConstraint(
                condition=Q(rescheduled_from__isnull=True) | ~Q(rescheduled_from=F("id")),
                name="appointment_rescheduled_from_not_self",
            ),
            PostgresExclusionConstraint(
                name="appointment_exclude_overlapping_worker",
                expressions=[
                    ("worker", RangeOperators.EQUAL),
                    (TsTzRange("start_at", "end_at"), RangeOperators.OVERLAPS),
                ],
                condition=Q(status__in=OCCUPYING_STATUSES),
            ),
        ]

    def __str__(self) -> str:
        return f"Cita {self.id} - {self.requester} - {self.service} ({self.get_status_display()})"

    def clean(self) -> None:
        super().clean()
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError("La fecha de fin debe ser posterior a la fecha de inicio.")
        if self.status == AppointmentStatus.CONFIRMED and self.worker is None:
            raise ValidationError("Una cita confirmada debe tener un trabajador asignado.")
        if self.status == AppointmentStatus.WAITLISTED and self.worker is not None:
            raise ValidationError(
                "Una cita en lista de espera no debe tener un trabajador asignado."
            )
        if self.rescheduled_from_id and self.rescheduled_from_id == self.id:
            raise ValidationError("Una cita no puede ser su propio origen de reprogramación.")

    @property
    def rescheduled_to(self) -> "Appointment | None":
        """Return the appointment that was rescheduled from this one, if any."""
        return self.rescheduled_children.first()
