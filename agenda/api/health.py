"""Health check and readiness endpoints for service monitoring."""

from django.core.cache import cache
from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Liveness check confirming that the HTTP application process is responsive."""

    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request: Request, *args, **kwargs) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class HealthReadyView(APIView):
    """Readiness check validating connectivity to critical dependencies (database and cache)."""

    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request: Request, *args, **kwargs) -> Response:
        failing: list[str] = []

        # Check database connectivity
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            failing.append("database")

        # Check cache connectivity
        try:
            cache_key = "_health_ready_check"
            cache.set(cache_key, "ok", timeout=5)
            val = cache.get(cache_key)
            if val != "ok":
                failing.append("cache")
        except Exception:
            failing.append("cache")

        if failing:
            return Response(
                {
                    "status": "unavailable",
                    "failing": failing,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"status": "ok"}, status=status.HTTP_200_OK)
