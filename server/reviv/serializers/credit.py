"""DRF serializers for credit packs and credit transactions."""

from rest_framework import serializers
from reviv.models import CreditPack, CreditTransaction


class CreditPackSerializer(serializers.ModelSerializer):
    """Serializer for CreditPack model"""

    price_dollars = serializers.SerializerMethodField()

    class Meta:
        model = CreditPack
        fields = [
            'id',
            'sku',
            'credits',
            'price_cents',
            'price_dollars',
            'active',
        ]
        read_only_fields = fields

    def get_price_dollars(self, obj):
        """Convert the pack price from cents to a display string in dollars."""
        return f"${obj.price_cents / 100:.2f}"


class CreditTransactionSerializer(serializers.ModelSerializer):
    """Serializer for CreditTransaction model"""

    class Meta:
        model = CreditTransaction
        fields = [
            'id',
            'amount',
            'transaction_type',
            'created_at',
        ]
        read_only_fields = fields


class PurchaseRequestSerializer(serializers.Serializer):
    """Serializer for credit pack purchase request"""

    sku = serializers.CharField(max_length=50)

    def validate_sku(self, value):
        """Validate that the requested SKU exists and the pack is active."""
        try:
            pack = CreditPack.objects.get(sku=value, active=True)
        except CreditPack.DoesNotExist:
            raise serializers.ValidationError("Invalid or inactive credit pack")
        return value