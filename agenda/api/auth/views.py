"""Authentication API views for JWT token issuing, refresh, revocation, and profile."""

import hashlib
import time

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from agenda.api.auth.serializers import (
    LoginResponseSerializer,
    LoginSerializer,
    LogoutSerializer,
    MeResponseSerializer,
    TokenRefreshResponseSerializer,
    TokenRefreshSerializer,
)
from agenda.api.roles import Role, get_user_role
from agenda.api.schemas import ErrorResponseSerializer
from agenda.api.throttling import AuthRateThrottle, UserRateThrottle
from agenda.logging import log_event


def _get_user_hash(username: str) -> str:
    return hashlib.sha256(username.lower().strip().encode("utf-8")).hexdigest()


def _get_lockout_key(username: str) -> str:
    return f"auth_lockout_{_get_user_hash(username)}"


def _get_attempts_key(username: str) -> str:
    return f"auth_attempts_{_get_user_hash(username)}"


class LoginView(APIView):
    """Authenticate staff and workers with username and password, issuing JWT tokens."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(
        summary="Iniciar sesión (Obtener tokens JWT)",
        description=(
            "Autentica usuarios con usuario y contraseña. Devuelve tokens de acceso y refresco. "
            "Tras 5 intentos fallidos para un mismo usuario, se bloquea por 15 minutos."
        ),
        request=LoginSerializer,
        responses={
            200: LoginResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Autenticación"],
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Datos de acceso inválidos.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        user_hash = _get_user_hash(username)[:8]
        lockout_key = _get_lockout_key(username)
        attempts_key = _get_attempts_key(username)

        lockout_until = cache.get(lockout_key)
        now_ts = time.time()
        if lockout_until is not None:
            remaining = int(lockout_until - now_ts)
            if remaining > 0:
                response = Response(
                    {
                        "code": "LOGIN_LOCKED",
                        "detail": "Demasiados intentos fallidos. Intente más tarde.",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
                response["Retry-After"] = str(remaining)
                return response
            cache.delete(lockout_key)

        user = authenticate(request, username=username, password=password)

        if user is None or not user.is_active:
            max_attempts = getattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 5)
            lockout_mins = getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15)
            lockout_secs = lockout_mins * 60

            attempts = cache.get(attempts_key, 0) + 1
            if attempts >= max_attempts:
                cache.set(lockout_key, now_ts + lockout_secs, timeout=lockout_secs)
                cache.delete(attempts_key)
                log_event("login_locked", user_hash=user_hash)
                response = Response(
                    {
                        "code": "LOGIN_LOCKED",
                        "detail": "Demasiados intentos fallidos. Intente más tarde.",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
                response["Retry-After"] = str(lockout_secs)
                return response

            cache.set(attempts_key, attempts, timeout=lockout_secs)
            log_event("login_failed", user_hash=user_hash)
            return Response(
                {
                    "code": "INVALID_CREDENTIALS",
                    "detail": "Credenciales de acceso inválidas.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        cache.delete(attempts_key)
        cache.delete(lockout_key)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class TokenRefreshCustomView(APIView):
    """Refresh JWT access token with rotation and blacklisting."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(
        summary="Refrescar token de acceso",
        description="Genera un nuevo token de acceso a partir de un token de refresco válido con rotación.",
        request=TokenRefreshSerializer,
        responses={
            200: TokenRefreshResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Autenticación"],
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = TokenRefreshSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Token de refresco requerido.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_refresh = serializer.validated_data["refresh"]
        try:
            token = RefreshToken(raw_refresh)
            token.check_blacklist()
            data = {"access": str(token.access_token)}

            if getattr(settings, "SIMPLE_JWT", {}).get("ROTATE_REFRESH_TOKENS", True):
                if getattr(settings, "SIMPLE_JWT", {}).get("BLACKLIST_AFTER_ROTATION", True):
                    try:
                        token.blacklist()
                    except (AttributeError, Exception):
                        pass
                token.set_jti()
                token.set_exp()
                token.set_iat()
                data["refresh"] = str(token)

            return Response(data, status=status.HTTP_200_OK)
        except (TokenError, InvalidToken, Exception):
            return Response(
                {
                    "code": "INVALID_TOKEN",
                    "detail": "Token inválido o expirado.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )


class LogoutView(APIView):
    """Revoke refresh token by adding it to the blacklist."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(
        summary="Cerrar sesión (Invalidar token de refresco)",
        description="Revoca el token de refresco agregándolo a la lista negra (blacklist).",
        request=LogoutSerializer,
        responses={
            204: None,
            400: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Autenticación"],
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = LogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "INVALID_PARAMETERS",
                    "detail": "Token de refresco requerido para cerrar sesión.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_refresh = serializer.validated_data["refresh"]
        try:
            token = RefreshToken(raw_refresh)
            token.blacklist()
        except Exception:
            pass

        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Retrieve current authenticated user information and effective role."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    @extend_schema(
        summary="Perfil del usuario autenticado",
        description="Retorna el identificador, nombre de usuario, rol efectivo y worker_id vinculado.",
        responses={
            200: MeResponseSerializer,
            401: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Autenticación"],
    )
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        role = get_user_role(user)

        worker = getattr(user, "worker_profile", None)
        worker_id = worker.id if worker is not None else None

        data = {
            "id": user.id,
            "username": user.username,
            "role": role.value if role != Role.ANONYMOUS else Role.NONE.value,
            "worker_id": worker_id,
        }
        serializer = MeResponseSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
