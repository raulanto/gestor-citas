"""Django admin forms for agenda models."""

from django import forms

from agenda.admin.mixins import _get_request_actor
from agenda.exceptions import DomainError
from agenda.models import Appointment, Requester, Service
from agenda.services import book_appointment


class AppointmentCreationForm(forms.ModelForm):
    """Admin form for booking a new appointment through domain service orchestration."""

    class Meta:
        model = Appointment
        fields = ("requester", "service", "start_at")

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
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
            except DomainError as exc:
                raise forms.ValidationError(exc.detail) from exc
            except Exception as exc:
                raise forms.ValidationError(str(exc)) from exc

        return cleaned_data

    def save(self, commit=True):
        if self._booking_result:
            return self._booking_result.appointment
        return super().save(commit=commit)
