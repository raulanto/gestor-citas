"""API views for agenda microapp."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Health check endpoint confirming API availability."""

    authentication_classes = []
    permission_classes = []

    def get(self, request, *args, **kwargs) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)
