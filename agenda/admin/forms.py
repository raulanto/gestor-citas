"""Django admin forms for agenda models."""

import datetime

from django import forms
from django.contrib.admin import widgets

from agenda.admin.mixins import _get_request_actor
from agenda.exceptions import DomainError
from agenda.models import Appointment, Requester, Service
from agenda.services import book_appointment


class AppointmentCreationForm(forms.ModelForm):
    """Admin form for booking a new appointment through domain service orchestration."""

    start_at = forms.SplitDateTimeField(
        label="Fecha y hora de inicio",
        widget=widgets.AdminSplitDateTime,
        help_text="Seleccione fecha y hora para la cita.",
    )

    class Meta:
        model = Appointment
        fields = ("requester", "service", "start_at")

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        if "data" in kwargs and kwargs["data"]:
            data = (
                kwargs["data"].copy() if hasattr(kwargs["data"], "copy") else dict(kwargs["data"])
            )
            if "start_at" in data and ("start_at_0" not in data or not data.get("start_at_0")):
                val = data["start_at"]
                if isinstance(val, (datetime.datetime, datetime.date)):
                    data["start_at_0"] = val.strftime("%Y-%m-%d")
                    data["start_at_1"] = val.strftime("%H:%M:%S")
                elif isinstance(val, str) and " " in val:
                    parts = val.split(" ", 1)
                    data["start_at_0"] = parts[0]
                    data["start_at_1"] = parts[1]
                elif isinstance(val, str) and "T" in val:
                    parts = val.split("T", 1)
                    data["start_at_0"] = parts[0]
                    data["start_at_1"] = parts[1].rstrip("Z")
            kwargs["data"] = data

        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["requester"].queryset = Requester.objects.filter(anonymized_at__isnull=True)
        self._booking_result = None

    def clean(self):
        cleaned_data = super().clean()
        requester = cleaned_data.get("requester")
        service = cleaned_data.get("service")
        start_at = cleaned_data.get("start_at")

        if requester and service and start_at:
            actor = _get_request_actor(self.request) if self.request else None
            try:
                self._booking_result = book_appointment(
                    requester=requester,
                    service=service,
                    start_at=start_at,
                    actor=actor,
                )
                self.instance = self._booking_result.appointment
            except DomainError as exc:
                raise forms.ValidationError(exc.detail) from exc
            except Exception as exc:
                raise forms.ValidationError(str(exc)) from exc

        return cleaned_data

    def save_m2m(self) -> None:
        """No-op for domain-orchestrated appointment booking."""
        pass

    def save(self, commit=True):
        self.save_m2m = lambda: None
        if self._booking_result:
            self.instance = self._booking_result.appointment
            return self._booking_result.appointment
        return super().save(commit=commit)
