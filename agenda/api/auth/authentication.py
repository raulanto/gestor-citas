"""Custom JWT authentication that records user ID and simplified role in request logging context."""

from rest_framework_simplejwt.authentication import JWTAuthentication

from agenda.logging import role_ctx_var, user_id_ctx_var


class CustomJWTAuthentication(JWTAuthentication):
    """Custom JWT authentication that propagates auth info to structured logging context."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, token = result
            user_id_ctx_var.set(user.pk)
            role = "STAFF" if (user.is_staff or user.is_superuser) else "USER"
            role_ctx_var.set(role)
        return result
