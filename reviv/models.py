import uuid

from django.contrib.auth.models import User
from django.db import models


class PhotoRestoration(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="restorations"
    )
    original_image = models.ImageField(upload_to="originals/")
    enhanced_image = models.ImageField(upload_to="enhanced/", blank=True, null=True)
    prompt = models.TextField(blank=True)
    kie_task_id = models.CharField(max_length=128, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Restoration {self.id} - {self.user.email} - {self.status}"
