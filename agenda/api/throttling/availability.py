"""Rate throttle for day availability queries."""

from typing import Any

from rest_framework.request import Request

from .base import ConfigurableThrottle


class AvailabilityRateThrottle(ConfigurableThrottle):
    """Rate throttle for checking day availability (by IP)."""

    scope = "availability"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
