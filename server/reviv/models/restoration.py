"""Restoration job database model.

This module defines the `RestorationJob` model used to track the lifecycle of an
image restoration request (upload -> processing -> completed/failed) and its
unlock status.
"""

from django.db import models
from django.conf import settings


class RestorationJob(models.Model):
    """Image restoration job tracking"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    UNLOCK_CHOICES = [
        ('paid', 'Paid'),
        ('social_share', 'Social Share'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='restoration_jobs'
    )
    original_image_url = models.URLField(
        help_text="Cloudinary URL of original uploaded image"
    )
    restored_preview_url = models.URLField(
        null=True,
        blank=True,
        help_text="Cloudinary URL of watermarked preview"
    )
    restored_full_url = models.URLField(
        null=True,
        blank=True,
        help_text="Cloudinary URL of full-resolution restored image"
    )
    kie_task_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Task ID from kie.ai API"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    unlock_method = models.CharField(
        max_length=20,
        choices=UNLOCK_CHOICES,
        null=True,
        blank=True,
        help_text="How the image was unlocked"
    )
    unlocked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the full image was unlocked"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        help_text="When this job should be deleted (60 days from creation)"
    )

    class Meta:
        db_table = 'restoration_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        """Return a human-readable representation of the job."""
        return f"Job {self.id} - {self.status} ({self.user.email})"

    @property
    def is_unlocked(self):
        """Return True if the job has been unlocked and a full image may be served."""
        return self.unlocked_at is not None