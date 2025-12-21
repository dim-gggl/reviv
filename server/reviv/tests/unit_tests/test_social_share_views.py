from datetime import timedelta
from urllib.parse import urlparse

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from reviv.models import RestorationJob, User


class SocialShareViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        self.client.force_authenticate(user=self.user)

    def _create_completed_job(self):
        return RestorationJob.objects.create(
            user=self.user,
            original_image_url="https://cloudinary.com/original.jpg",
            restored_full_url="https://cloudinary.com/full.jpg",
            status="completed",
            expires_at=timezone.now() + timedelta(days=60),
        )

    def test_share_unlock_returns_urls(self):
        job = self._create_completed_job()

        response = self.client.post(f"/api/restorations/{job.id}/share-unlock/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("facebook", response.data)
        self.assertIn("twitter", response.data)
        self.assertIn("linkedin", response.data)
        self.assertIn("pinterest", response.data)
        self.assertIn("instagram", response.data)
        self.assertEqual(response.data["instagram"]["type"], "manual")
        self.assertIn("/api/restorations/", response.data["twitter"])
        self.assertIn("/share-redirect/twitter/", response.data["twitter"])
        self.assertIn("s=", response.data["twitter"])

    def test_share_unlock_already_unlocked(self):
        job = self._create_completed_job()
        job.unlock_method = "paid"
        job.unlocked_at = timezone.now()
        job.save(update_fields=["unlock_method", "unlocked_at"])

        response = self.client.post(f"/api/restorations/{job.id}/share-unlock/")

        self.assertEqual(response.status_code, 409)

    def test_share_unlock_already_used(self):
        job = self._create_completed_job()
        self.user.social_share_unlock_used = True
        self.user.save(update_fields=["social_share_unlock_used"])

        response = self.client.post(f"/api/restorations/{job.id}/share-unlock/")

        self.assertEqual(response.status_code, 403)

    def test_share_unlock_not_completed(self):
        job = RestorationJob.objects.create(
            user=self.user,
            original_image_url="https://cloudinary.com/original.jpg",
            status="processing",
            expires_at=timezone.now() + timedelta(days=60),
        )

        response = self.client.post(f"/api/restorations/{job.id}/share-unlock/")

        self.assertEqual(response.status_code, 400)

    def test_confirm_share_success(self):
        job = self._create_completed_job()

        share_response = self.client.post(f"/api/restorations/{job.id}/share-unlock/")
        redirect_url = share_response.data["twitter"]
        parsed = urlparse(redirect_url)
        redirect_path = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        redirect_response = self.client.get(redirect_path, follow=False)
        self.assertEqual(redirect_response.status_code, 302)

        response = self.client.post(f"/api/restorations/{job.id}/confirm-share/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["full_image_url"], "https://cloudinary.com/full.jpg")
        job.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(job.unlock_method, "social_share")
        self.assertTrue(job.unlocked_at)
        self.assertTrue(self.user.social_share_unlock_used)

    def test_confirm_share_requires_redirect(self):
        job = self._create_completed_job()

        self.client.post(f"/api/restorations/{job.id}/share-unlock/")
        response = self.client.post(f"/api/restorations/{job.id}/confirm-share/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "SHARE_NOT_INITIATED")

    def test_confirm_share_already_used(self):
        job = self._create_completed_job()
        self.user.social_share_unlock_used = True
        self.user.save(update_fields=["social_share_unlock_used"])

        response = self.client.post(f"/api/restorations/{job.id}/confirm-share/")

        self.assertEqual(response.status_code, 403)

    def test_confirm_share_already_unlocked(self):
        job = self._create_completed_job()
        job.unlock_method = "paid"
        job.unlocked_at = timezone.now()
        job.save(update_fields=["unlock_method", "unlocked_at"])

        response = self.client.post(f"/api/restorations/{job.id}/confirm-share/")

        self.assertEqual(response.status_code, 409)

    def test_confirm_share_job_not_found(self):
        response = self.client.post("/api/restorations/999/confirm-share/")

        self.assertEqual(response.status_code, 404)
