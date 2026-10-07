"""Worker model representing staff members attending appointments."""

from django.conf import settings
from django.db import models


class Worker(models.Model):
    """Staff member who attends appointments according to their work schedule."""

    full_name = models.CharField("nombre completo", max_length=150)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worker_profile",
        verbose_name="usuario del sistema",
    )
    is_active = models.BooleanField("activo", default=True)

    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        verbose_name = "trabajador"
        verbose_name_plural = "trabajadores"
        ordering = ["full_name"]

    def __str__(self) -> str:
        return self.full_name
