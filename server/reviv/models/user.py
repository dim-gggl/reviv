"""Custom user model used by the `reviv` Django app.

The project enforces passwordless authentication (OAuth and/or passkeys). This
module extends Django's `AbstractUser` to store OAuth identifiers and credit-
related flags used by the product.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from decimal import Decimal


class User(AbstractUser):
    """Custom user model for passwordless authentication (Google OAuth or Email/Passkey only)"""

    oauth_provider = models.CharField(
        max_length=20,
        blank=True,
        help_text="OAuth provider: google, apple, microsoft or facebook."
    )
    oauth_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="OAuth id: google id, apple id, microsoft id or facebook id."
    )
    credit_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Number of credits available for unlocking image restorations."
    )
    free_preview_used = models.BooleanField(
        default=False,
        help_text="Whether the user has used their one free preview."
    )
    social_share_unlock_used = models.BooleanField(
        default=False,
        help_text="Whether the user has used their one-time social media share unlock."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["oauth_provider", "oauth_id"]),
        ]

    def save(self, *args, **kwargs):
        """Override save to ensure users have unusable passwords by default (passwordless auth)"""
        if self._state.adding and not self.password:
            self.set_unusable_password()
        super().save(*args, **kwargs)

    def __str__(self):
        """Return a human-readable identifier for the user."""
        return self.email or self.username