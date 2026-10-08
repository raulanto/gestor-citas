"""Base rate throttle class configurable via Django settings."""

from typing import Any

from django.conf import settings
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class ConfigurableThrottle(SimpleRateThrottle):
    """Base throttle class that can be globally toggled via THROTTLING_ENABLED setting."""

    def get_rate(self) -> str | None:
        drf_settings = getattr(settings, "REST_FRAMEWORK", {})
        rates = drf_settings.get("DEFAULT_THROTTLE_RATES", {})
        if self.scope in rates:
            return rates[self.scope]
        return super().get_rate()

    def allow_request(self, request: Request, view: Any) -> bool:
        if not getattr(settings, "THROTTLING_ENABLED", True):
            return True
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)
