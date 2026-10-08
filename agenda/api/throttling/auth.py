"""Rate throttle for authentication endpoints."""

from typing import Any

from rest_framework.request import Request

from .base import ConfigurableThrottle


class AuthRateThrottle(ConfigurableThrottle):
    """Rate throttle for authentication endpoints (by IP)."""

    scope = "auth"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
