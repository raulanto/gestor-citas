"""Serializers for requester inputs and details across roles."""

from rest_framework import serializers


class RequesterInputSerializer(serializers.Serializer):
    """Input serializer for requester contact details in appointment booking."""

    full_name = serializers.CharField(
        max_length=150,
        required=True,
        error_messages={"required": "El nombre completo del solicitante es obligatorio."},
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs: dict) -> dict:
        phone = (attrs.get("phone") or "").strip()
        email = (attrs.get("email") or "").strip()
        if not phone and not email:
            raise serializers.ValidationError(
                "Debe proporcionar al menos un teléfono o un correo electrónico."
            )
        return attrs


class RequesterPublicDetailSerializer(serializers.Serializer):
    """Public requester serializer with minimal personal data (no phone, no email)."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()


class RequesterWorkerDetailSerializer(serializers.Serializer):
    """Worker requester serializer with contact phone for appointment fulfillment (no email)."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    phone = serializers.CharField()


class RequesterDetailSerializer(serializers.Serializer):
    """Staff full requester detail serializer with all contact information."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.EmailField()
