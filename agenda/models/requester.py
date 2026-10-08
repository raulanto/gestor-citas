"""Requester model representing the person requesting an appointment."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Requester(models.Model):
    """Person who requests an appointment."""

    full_name = models.CharField("nombre completo", max_length=150)
    phone = models.CharField("teléfono", max_length=30, blank=True, default="")
    email = models.EmailField("correo electrónico", blank=True, default="")
    anonymized_at = models.DateTimeField("anonimizado el", null=True, blank=True, db_index=True)

    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        verbose_name = "solicitante"
        verbose_name_plural = "solicitantes"
        ordering = ["full_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(anonymized_at__isnull=False) | (~Q(phone="") | ~Q(email="")),
                name="requester_phone_or_email_required",
            ),
        ]

    def __str__(self) -> str:
        return self.full_name

    def clean(self) -> None:
        super().clean()
        if self.anonymized_at is None:
            phone_val = (self.phone or "").strip()
            email_val = (self.email or "").strip()
            if not phone_val and not email_val:
                raise ValidationError(
                    "Debe proporcionar al menos un teléfono o un correo electrónico."
                )
