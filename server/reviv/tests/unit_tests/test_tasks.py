from datetime import timedelta
from io import BytesIO
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from reviv.models import RestorationJob, User
from reviv.tasks.cleanup import cleanup_expired_restorations, cleanup_failed_jobs
from reviv.tasks.restoration import process_restoration


class RestorationTaskTest(TestCase):
    @patch("reviv.tasks.restoration.cloudinary.uploader.upload")
    @patch("reviv.tasks.restoration.requests.get")
    @patch("reviv.tasks.restoration.kie_client.wait_for_completion")
    @patch("reviv.tasks.restoration.kie_client.create_task")
    def test_process_restoration_success(
        self,
        mock_create_task,
        mock_wait_for_completion,
        mock_get,
        mock_upload,
    ):
        user = User.objects.create(email="test@example.com", username="test@example.com")
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://example.com/original.jpg",
            expires_at=timezone.now() + timedelta(days=60),
        )
        mock_create_task.return_value = {"taskId": "task_123"}
        mock_wait_for_completion.return_value = {"state": "success", "output": ["https://output.png"]}
        mock_response = Mock()
        mock_response.content = BytesIO(b"fake-image").getvalue()
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        mock_upload.side_effect = [
            {"secure_url": "https://preview.jpg"},
            {"secure_url": "https://full.jpg"},
        ]

        process_restoration(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.kie_task_id, "task_123")
        self.assertEqual(job.restored_preview_url, "https://preview.jpg")
        self.assertEqual(job.restored_full_url, "https://full.jpg")
        self.assertEqual(mock_upload.call_count, 2)

    @patch("reviv.tasks.restoration.kie_client.wait_for_completion")
    @patch("reviv.tasks.restoration.kie_client.create_task")
    def test_process_restoration_failed_state(self, mock_create_task, mock_wait_for_completion):
        user = User.objects.create(email="test@example.com", username="test@example.com")
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://example.com/original.jpg",
            expires_at=timezone.now() + timedelta(days=60),
        )
        mock_create_task.return_value = {"taskId": "task_123"}
        mock_wait_for_completion.return_value = {"state": "failed", "error": "fail"}

        process_restoration(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "failed")

    @patch("reviv.tasks.restoration.kie_client.wait_for_completion", side_effect=TimeoutError)
    @patch("reviv.tasks.restoration.kie_client.create_task")
    def test_process_restoration_timeout(self, mock_create_task, _mock_wait_for_completion):
        user = User.objects.create(email="test@example.com", username="test@example.com")
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://example.com/original.jpg",
            expires_at=timezone.now() + timedelta(days=60),
        )
        mock_create_task.return_value = {"taskId": "task_123"}

        process_restoration(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "failed")


class CleanupTasksTest(TestCase):
    @patch("reviv.tasks.cleanup.cloudinary.uploader.destroy")
    def test_cleanup_expired_restorations(self, mock_destroy):
        user = User.objects.create(email="test@example.com", username="test@example.com")
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://res.cloudinary.com/demo/image/upload/v1234/reviv/original.jpg",
            restored_preview_url="https://res.cloudinary.com/demo/image/upload/v1234/reviv/preview.jpg",
            restored_full_url="https://res.cloudinary.com/demo/image/private/v1234/reviv/full.jpg",
            status="completed",
            expires_at=timezone.now() - timedelta(days=1),
        )

        count = cleanup_expired_restorations()

        self.assertEqual(count, 1)
        self.assertFalse(RestorationJob.objects.filter(id=job.id).exists())
        self.assertGreaterEqual(mock_destroy.call_count, 2)

    @patch("reviv.tasks.cleanup.cloudinary.uploader.destroy")
    def test_cleanup_failed_jobs(self, mock_destroy):
        user = User.objects.create(email="test@example.com", username="test@example.com")
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://res.cloudinary.com/demo/image/upload/v1234/reviv/original.jpg",
            status="failed",
            expires_at=timezone.now() + timedelta(days=60),
        )
        RestorationJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(days=2)
        )

        count = cleanup_failed_jobs()

        self.assertEqual(count, 1)
        self.assertFalse(RestorationJob.objects.filter(id=job.id).exists())
        self.assertGreaterEqual(mock_destroy.call_count, 1)
