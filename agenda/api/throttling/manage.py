"""Rate throttle for requester operations with manage token."""

from typing import Any

from rest_framework.request import Request

from .base import ConfigurableThrottle


class ManageRateThrottle(ConfigurableThrottle):
    """Rate throttle for requester operations using X-Manage-Token (by IP)."""

    scope = "manage"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
