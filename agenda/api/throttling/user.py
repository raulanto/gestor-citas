"""Rate throttle for authenticated users."""

from typing import Any

from rest_framework.request import Request

from .base import ConfigurableThrottle


class UserRateThrottle(ConfigurableThrottle):
    """Rate throttle for authenticated staff and worker requests (by user_id)."""

    scope = "user"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        if request.user and request.user.is_authenticated:
            return self.cache_format % {"scope": self.scope, "ident": str(request.user.pk)}
        return None
