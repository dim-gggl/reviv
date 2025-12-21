from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from reviv.models import RestorationJob, User


class RestorationViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        self.client.force_authenticate(user=self.user)

    def _make_image_file(self):
        buffer = BytesIO()
        image = Image.new("RGB", (800, 800), color="red")
        image.save(buffer, format="JPEG")
        buffer.seek(0)
        return SimpleUploadedFile("test.jpg", buffer.read(), content_type="image/jpeg")

    @patch("reviv.views.restoration.process_restoration.delay")
    @patch("reviv.views.restoration.cloudinary.uploader.upload")
    def test_upload_image_success(self, mock_upload, mock_delay):
        mock_upload.return_value = {"secure_url": "https://cloudinary.com/original.jpg"}

        response = self.client.post(
            "/api/restorations/upload/",
            {"image": self._make_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("job_id", response.data)
        self.assertEqual(response.data["status"], "pending")
        job = RestorationJob.objects.get(id=response.data["job_id"])
        self.assertEqual(job.original_image_url, "https://cloudinary.com/original.jpg")
        mock_delay.assert_called_once_with(job.id)

    @patch("reviv.views.restoration.cloudinary.uploader.upload")
    def test_upload_image_history_limit(self, _mock_upload):
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

    def test_restoration_status_completed(self):
        job = RestorationJob.objects.create(
            user=self.user,
            original_image_url="https://cloudinary.com/original.jpg",
            restored_preview_url="https://cloudinary.com/preview.jpg",
            status="completed",
            expires_at=timezone.now() + timedelta(days=60),
        )

        response = self.client.get(f"/api/restorations/{job.id}/status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["preview_url"], "https://cloudinary.com/preview.jpg")

    def test_restoration_status_not_found(self):
        response = self.client.get("/api/restorations/999/status/")

        self.assertEqual(response.status_code, 404)

    def test_restoration_history_returns_jobs(self):
        for _ in range(2):
            RestorationJob.objects.create(
                user=self.user,
                original_image_url="https://cloudinary.com/original.jpg",
                expires_at=timezone.now() + timedelta(days=60),
            )

        response = self.client.get("/api/restorations/history/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    @patch("reviv.views.restoration.cloudinary.uploader.destroy")
    def test_delete_restoration(self, mock_destroy):
        job = RestorationJob.objects.create(
            user=self.user,
            original_image_url="https://res.cloudinary.com/demo/image/upload/v1234/reviv/original.jpg",
            restored_preview_url="https://res.cloudinary.com/demo/image/upload/v1234/reviv/preview.jpg",
            restored_full_url="https://res.cloudinary.com/demo/image/private/v1234/reviv/full.jpg",
            status="completed",
            expires_at=timezone.now() + timedelta(days=60),
        )

        response = self.client.delete(f"/api/restorations/{job.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(RestorationJob.objects.filter(id=job.id).exists())
        self.assertGreaterEqual(mock_destroy.call_count, 2)

    def test_delete_restoration_not_found(self):
        response = self.client.delete("/api/restorations/999/")

        self.assertEqual(response.status_code, 404)
