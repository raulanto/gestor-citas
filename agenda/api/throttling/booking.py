"""Rate throttles for appointment booking (by IP and hashed contact)."""

import hashlib
from typing import Any

from rest_framework.request import Request

from agenda.services.requesters import normalize_phone

from .base import ConfigurableThrottle


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
