"""Configurable rate throttling classes for API abuse protection."""

import hashlib
from typing import Any

from django.conf import settings
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle

from agenda.services.requesters import normalize_phone


class ConfigurableThrottle(SimpleRateThrottle):
    """Base throttle class that can be globally toggled via THROTTLING_ENABLED setting."""

    def allow_request(self, request: Request, view: Any) -> bool:
        if not getattr(settings, "THROTTLING_ENABLED", True):
            return True
        return super().allow_request(request, view)


class AvailabilityRateThrottle(ConfigurableThrottle):
    """Rate throttle for checking day availability (by IP)."""

    scope = "availability"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class BookingMinuteRateThrottle(ConfigurableThrottle):
    """Per-minute rate throttle for booking appointments (by IP)."""

    scope = "booking_minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class BookingHourRateThrottle(ConfigurableThrottle):
    """Per-hour rate throttle for booking appointments (by IP)."""

    scope = "booking_hour"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class BookingContactRateThrottle(ConfigurableThrottle):
    """Per-hour rate throttle for booking appointments by hashed contact (phone or email).

    Ensures that formatted variations of phone and emails share the same quota
    and never stores personal information in plain text cache keys.
    """

    scope = "booking_contact"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        if not isinstance(request.data, dict):
            return None

        requester_data = request.data.get("requester")
        if not isinstance(requester_data, dict):
            return None

        phone = normalize_phone(requester_data.get("phone"))
        email = (requester_data.get("email") or "").strip().lower()

        contact = phone or email
        if not contact:
            return None

        contact_hash = hashlib.sha256(contact.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": contact_hash}


class ManageRateThrottle(ConfigurableThrottle):
    """Rate throttle for requester operations using X-Manage-Token (by IP)."""

    scope = "manage"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AuthRateThrottle(ConfigurableThrottle):
    """Rate throttle for authentication endpoints (by IP)."""

    scope = "auth"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class UserRateThrottle(ConfigurableThrottle):
    """Rate throttle for authenticated staff and worker requests (by user_id)."""

    scope = "user"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        if request.user and request.user.is_authenticated:
            return self.cache_format % {"scope": self.scope, "ident": str(request.user.pk)}
        return None
