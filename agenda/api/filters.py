"""Filter sets for queryable endpoints using django-filter."""

import datetime

import django_filters
from rest_framework.exceptions import ValidationError

from agenda.constants import AppointmentStatus
from agenda.models import Appointment
from agenda.selectors.schedules import list_unserviceable_waitlist


class AppointmentFilter(django_filters.FilterSet):
    """Filter set for Staff appointment listing."""

    date = django_filters.DateFilter(field_name="date")
    date_from = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="date", lookup_expr="lte")
    status = django_filters.MultipleChoiceFilter(
        field_name="status",
        choices=AppointmentStatus.choices,
    )
    worker = django_filters.NumberFilter(field_name="worker_id")
    service = django_filters.NumberFilter(field_name="service_id")
    unserviceable = django_filters.BooleanFilter(method="filter_unserviceable")
    ordering = django_filters.OrderingFilter(
        fields=(
            ("start_at", "start_at"),
            ("created_at", "created_at"),
        ),
    )

    class Meta:
        model = Appointment
        fields = [
            "date",
            "date_from",
            "date_to",
            "status",
            "worker",
            "service",
            "unserviceable",
            "ordering",
        ]

    def filter_unserviceable(self, queryset, name, value):
        if value:
            date_param = self.data.get("date") or self.data.get("date_from")
            from_date = None
            if date_param:
                try:
                    from_date = datetime.date.fromisoformat(date_param)
                except ValueError:
                    pass
            unserviceable_appts = list_unserviceable_waitlist(from_date=from_date)
            unserviceable_ids = [appt.id for appt in unserviceable_appts]
            return queryset.filter(id__in=unserviceable_ids)
        return queryset

    @property
    def qs(self):
        # Validate ordering parameter against whitelist
        ordering_param = self.data.get("ordering")
        if ordering_param:
            allowed_orderings = {"start_at", "-start_at", "created_at", "-created_at"}
            requested_orderings = [o.strip() for o in ordering_param.split(",")]
            for o in requested_orderings:
                if o and o not in allowed_orderings:
                    raise ValidationError(f"Campo de ordenamiento '{o}' no permitido.")

        # Validate date range
        date_from_str = self.data.get("date_from")
        date_to_str = self.data.get("date_to")
        if date_from_str and date_to_str:
            try:
                d_from = datetime.date.fromisoformat(date_from_str)
                d_to = datetime.date.fromisoformat(date_to_str)
            except ValueError:
                raise ValidationError("Formato de fecha inválido. Utilice YYYY-MM-DD.") from None

            if d_to < d_from:
                raise ValidationError("date_to no puede ser anterior a date_from.")
            if (d_to - d_from).days > 92:
                raise ValidationError("El rango de fechas no puede exceder 92 días.")

        qs = super().qs
        if not ordering_param:
            qs = qs.order_by("start_at")
        return qs
