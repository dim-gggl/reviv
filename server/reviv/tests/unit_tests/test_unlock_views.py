from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from reviv.models import CreditTransaction, RestorationJob, User


class CreditUnlockViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
            credit_balance=Decimal("2.00"),
        )
        self.client.force_authenticate(user=self.user)

    def _create_completed_job(self):
        return RestorationJob.objects.create(
            user=self.user,
            original_image_url="https://cloudinary.com/original.jpg",
            restored_full_url="https://cloudinary.com/full.jpg",
            status="completed",
            expires_at=timezone.now() + timedelta(days=60),
        )

    def test_unlock_success(self):
        job = self._create_completed_job()

        response = self.client.post(f"/api/restorations/{job.id}/unlock/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["full_image_url"], "https://cloudinary.com/full.jpg")
        self.assertEqual(response.data["credits_remaining"], "1.00")
        job.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(job.unlock_method, "paid")
        self.assertTrue(job.unlocked_at)
        self.assertEqual(self.user.credit_balance, Decimal("1.00"))
        self.assertEqual(CreditTransaction.objects.filter(user=self.user).count(), 1)

    def test_unlock_insufficient_credits(self):
        job = self._create_completed_job()
        self.user.credit_balance = Decimal("0.00")
        self.user.save(update_fields=["credit_balance"])

        response = self.client.post(f"/api/restorations/{job.id}/unlock/")

        self.assertEqual(response.status_code, 403)

    def test_unlock_not_completed(self):
        job = RestorationJob.objects.create(
            user=self.user,
            original_image_url="https://cloudinary.com/original.jpg",
            status="processing",
            expires_at=timezone.now() + timedelta(days=60),
        )

        response = self.client.post(f"/api/restorations/{job.id}/unlock/")

        self.assertEqual(response.status_code, 400)

    def test_unlock_already_unlocked(self):
        job = self._create_completed_job()
        job.unlock_method = "paid"
        job.unlocked_at = timezone.now()
        job.save(update_fields=["unlock_method", "unlocked_at"])

        response = self.client.post(f"/api/restorations/{job.id}/unlock/")

        self.assertEqual(response.status_code, 409)

    def test_unlock_job_not_found(self):
        response = self.client.post("/api/restorations/999/unlock/")

        self.assertEqual(response.status_code, 404)
