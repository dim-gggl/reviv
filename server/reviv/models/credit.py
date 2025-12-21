from django.db import models
from django.conf import settings


class CreditPack(models.Model):
    """Available credit packs for purchase"""

    sku = models.CharField(
        max_length=50,
        unique=True,
        help_text="Stock keeping unit identifier"
    )
    credits = models.IntegerField(
        help_text="Number of credits in this pack"
    )
    price_cents = models.IntegerField(
        help_text="Price in cents (EUR)"
    )
    active = models.BooleanField(
        default=True,
        help_text="Whether this pack is currently available for purchase"
    )

    class Meta:
        db_table = 'credit_packs'
        ordering = ['credits']

    def __str__(self):
        return f"{self.sku} - {self.credits} credits ({self.price_cents/100:.2f}€)"


class CreditTransaction(models.Model):
    """Transaction history for credit purchases and usage"""

    TRANSACTION_TYPES = [
        ('purchase', 'Purchase'),
        ('unlock', 'Unlock'),
        ('refund', 'Refund'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_transactions'
    )
    amount = models.IntegerField(
        help_text="Positive for purchase/refund, negative for usage"
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES
    )
    stripe_payment_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="Stripe payment intent ID for purchases"
    )
    restoration_job = models.ForeignKey(
        'RestorationJob',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Associated restoration job for unlocks"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'credit_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['stripe_payment_id']),
        ]

    def __str__(self):
        return f"{self.transaction_type} - {self.amount} credits ({self.user.email})"