from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from reviv.models import RestorationJob, User


class ErrorFormattingTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        self.client.force_authenticate(user=self.user)

    def test_history_limit_error_format(self):
        for _ in range(6):
            RestorationJob.objects.create(
                user=self.user,
                original_image_url="https://cloudinary.com/original.jpg",
                expires_at=timezone.now() + timedelta(days=60),
            )

        response = self.client.post("/api/restorations/upload/", {})

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.data)
        self.assertIn("code", response.data["error"])
        self.assertIn("message", response.data["error"])
        self.assertIn("details", response.data["error"])

    def test_oauth_initiate_missing_provider_format(self):
        client = APIClient()
        response = client.post("/api/auth/oauth/initiate/", {})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
        self.assertIn("code", response.data["error"])
