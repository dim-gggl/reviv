from django.db import models
from django.conf import settings


class Passkey(models.Model):
    """WebAuthn passkey for user authentication"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='passkeys'
    )
    credential_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique credential ID from WebAuthn"
    )
    public_key = models.TextField(
        help_text="Public key credential data"
    )
    sign_count = models.IntegerField(
        default=0,
        help_text="Signature counter for replay attack prevention"
    )
    name = models.CharField(
        max_length=100,
        help_text="User-friendly device name"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'passkeys'
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.email})"