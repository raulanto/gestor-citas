"""Authentication serializers for login, token refresh, logout, and user profile."""

from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    """Input serializer for user login."""

    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class TokenRefreshSerializer(serializers.Serializer):
    """Input serializer for JWT token refresh."""

    refresh = serializers.CharField(required=True)


class LogoutSerializer(serializers.Serializer):
    """Input serializer for JWT logout / token revocation."""

    refresh = serializers.CharField(required=True)


class MeResponseSerializer(serializers.Serializer):
    """Output serializer for current authenticated user profile."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    role = serializers.CharField()
    worker_id = serializers.IntegerField(allow_null=True)
