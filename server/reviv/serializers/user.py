"""DRF serializers for user and passkey models."""

from rest_framework import serializers
from reviv.models import User, Passkey


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model"""

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'credit_balance',
            'free_preview_used',
            'social_share_unlock_used',
            'created_at',
        ]
        read_only_fields = fields


class PasskeySerializer(serializers.ModelSerializer):
    """Serializer for Passkey model"""

    class Meta:
        model = Passkey
        fields = [
            'id',
            'name',
            'created_at',
            'last_used_at',
        ]
        read_only_fields = fields