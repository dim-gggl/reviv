"""DRF serializers for image restoration workflows.

This module includes:
- a custom `ImageField` for consistent upload error messages
- serializers for upload requests, job representation, and status polling
"""

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers
from reviv.models import RestorationJob


class RestorationImageField(serializers.ImageField):
    """ImageField with project-specific, stable validation error messages."""

    default_error_messages = {
        "invalid_image": "Invalid image file",
    }


class RestorationJobSerializer(serializers.ModelSerializer):
    """Serializer for RestorationJob model"""

    is_unlocked = serializers.ReadOnlyField()

    class Meta:
        model = RestorationJob
        fields = [
            'id',
            'original_image_url',
            'restored_preview_url',
            'restored_full_url',
            'status',
            'unlock_method',
            'unlocked_at',
            'is_unlocked',
            'created_at',
            'expires_at',
        ]
        read_only_fields = [
            'id',
            'restored_preview_url',
            'restored_full_url',
            'status',
            'unlock_method',
            'unlocked_at',
            'is_unlocked',
            'created_at',
            'expires_at',
        ]


class RestorationUploadSerializer(serializers.Serializer):
    """Serializer for image upload"""

    image = RestorationImageField(
        max_length=None,
        allow_empty_file=False,
        use_url=True,
    )

    def validate_image(self, value):
        """Validate the uploaded image file (size, format, and dimensions)."""
        # Check file size (max 10MB)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("File must be under 10MB")

        # Check file format
        allowed_formats = ["JPEG", "JPG", "PNG", "WEBP"]
        try:
            img = Image.open(value)
            img.load()
        except UnidentifiedImageError:
            raise serializers.ValidationError("Invalid image file")
        except Exception:
            raise serializers.ValidationError("Invalid image file")
        try:
            if img.format not in allowed_formats:
                raise serializers.ValidationError("Only JPG, PNG, WEBP formats allowed")

            # Check dimensions (min 500px)
            min_dimension = min(img.width, img.height)
            if min_dimension < 500:
                raise serializers.ValidationError("Image must be at least 500px on shortest side")

        finally:
            try:
                value.seek(0)
            except Exception:
                pass

        return value


class RestorationStatusSerializer(serializers.Serializer):
    """Serializer for restoration status response"""

    job_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=['pending', 'processing', 'completed', 'failed'])
    preview_url = serializers.URLField(required=False, allow_null=True)
    error = serializers.CharField(required=False, allow_null=True)
