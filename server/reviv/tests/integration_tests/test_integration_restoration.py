from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from reviv.models import RestorationJob, User


class RestorationIntegrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
            credit_balance=Decimal("5.00"),
        )
        self.client.force_authenticate(user=self.user)

    def _make_image_file(self):
        buffer = BytesIO()
        image = Image.new("RGB", (800, 800), color="red")
        image.save(buffer, format="JPEG")
        buffer.seek(0)
        return SimpleUploadedFile("test.jpg", buffer.read(), content_type="image/jpeg")

    @patch("reviv.views.restoration.process_restoration.delay")
    @patch("reviv.views.restoration.cloudinary.uploader.upload")
    def test_complete_restoration_workflow(self, mock_upload, mock_delay):
        mock_upload.return_value = {"secure_url": "https://cloudinary.com/original.jpg"}

        response = self.client.post(
            "/api/restorations/upload/",
            {"image": self._make_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        job_id = response.data["job_id"]
        mock_delay.assert_called_once_with(job_id)

        job = RestorationJob.objects.get(id=job_id)
        job.status = "completed"
        job.restored_preview_url = "https://cloudinary.com/preview.jpg"
        job.restored_full_url = "https://cloudinary.com/full.jpg"
        job.save()

        response = self.client.get(f"/api/restorations/{job_id}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["preview_url"], "https://cloudinary.com/preview.jpg")

        response = self.client.post(f"/api/restorations/{job_id}/unlock/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["credits_remaining"], "4.00")

        response = self.client.get("/api/restorations/history/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_history_limit_enforcement(self):
        for _ in range(6):
            RestorationJob.objects.create(
                user=self.user,
                original_image_url="https://cloudinary.com/original.jpg",
                expires_at=timezone.now() + timedelta(days=60),
            )

        response = self.client.post(
            "/api/restorations/upload/",
            {"image": self._make_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 403)
