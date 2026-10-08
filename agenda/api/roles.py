"""Role definitions and role detection helper."""

from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """User roles for authentication and permission enforcement."""

    STAFF = "STAFF"
    WORKER = "WORKER"
    NONE = "NONE"
    ANONYMOUS = "ANONYMOUS"


def get_user_role(user: Any) -> Role:
    """Determine the effective role of a user.

    - STAFF: is_staff or is_superuser (retains staff role even if linked to a worker).
    - WORKER: has an active linked Worker profile.
    - NONE: authenticated user with neither staff nor active worker profile.
    - ANONYMOUS: unauthenticated request.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return Role.ANONYMOUS

    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return Role.STAFF

    worker = getattr(user, "worker_profile", None)
    if worker is not None and getattr(worker, "is_active", False):
        return Role.WORKER

    return Role.NONE
