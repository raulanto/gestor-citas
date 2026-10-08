"""Permission classes for role-based and manage-token access control."""

from django.http import Http404
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from agenda.api.roles import Role, get_user_role
from agenda.models import Appointment
from agenda.services.manage_token import verify_manage_token

PUBLIC_ENDPOINTS_WHITELIST = frozenset(
    {
        "health",
        "health_ready",
        "availability",
        "appointments",  # Only POST is public
        "auth_token",
        "auth_token_refresh",
        "auth_logout",
        "schema",
        "swagger_ui",
    }
)


class IsStaff(BasePermission):
    """Allows access only to authenticated staff users."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return get_user_role(request.user) == Role.STAFF


class IsWorker(BasePermission):
    """Allows access only to authenticated active workers."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return get_user_role(request.user) == Role.WORKER


class IsWorkerSelfOrStaff(BasePermission):
    """Allows access to staff or the specific worker identified in the URL kwargs."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        role = get_user_role(request.user)
        if role == Role.STAFF:
            return True
        if role == Role.WORKER:
            worker_id = view.kwargs.get("id")
            if worker_id is not None and request.user.worker_profile.id == int(worker_id):
                return True
        return False


class IsAppointmentWorkerOrStaff(BasePermission):
    """Allows access to staff or the worker assigned to the specific appointment object."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        role = get_user_role(request.user)
        return role in (Role.STAFF, Role.WORKER)

    def has_object_permission(self, request: Request, view: APIView, obj: Appointment) -> bool:
        role = get_user_role(request.user)
        if role == Role.STAFF:
            return True
        if role == Role.WORKER:
            worker = getattr(request.user, "worker_profile", None)
            return worker is not None and obj.worker_id == worker.id
        return False


class HasManageTokenOrStaff(BasePermission):
    """Allows access to staff, or requesters with a valid X-Manage-Token.

    Raises Http404 on missing or invalid token to prevent appointment enumeration.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return True

    def has_object_permission(self, request: Request, view: APIView, obj: Appointment) -> bool:
        role = get_user_role(request.user)
        if role == Role.STAFF:
            return True

        manage_token = request.headers.get("X-Manage-Token")
        if not manage_token:
            manage_token = request.META.get("HTTP_X_MANAGE_TOKEN")

        if manage_token and verify_manage_token(obj, manage_token):
            return True

        raise Http404("Appointment not found or manage token invalid.")
