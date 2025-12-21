from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from reviv.models import (
    CreditPack,
    CreditTransaction,
    Passkey,
    RestorationJob,
    User,
)


class UserModelTest(TestCase):
    def test_create_user_with_oauth_defaults(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
            oauth_provider="google",
            oauth_id="google_123",
        )

        self.assertEqual(user.oauth_provider, "google")
        self.assertEqual(user.oauth_id, "google_123")
        self.assertEqual(user.credit_balance, Decimal("0.00"))
        self.assertFalse(user.free_preview_used)
        self.assertFalse(user.social_share_unlock_used)

    def test_unique_oauth_id_is_enforced(self):
        User.objects.create(
            email="test1@example.com",
            username="test1@example.com",
            oauth_provider="google",
            oauth_id="google_123",
        )

        with self.assertRaises(IntegrityError):
            User.objects.create(
                email="test2@example.com",
                username="test2@example.com",
                oauth_provider="google",
                oauth_id="google_123",
            )

    def test_user_can_be_created_without_password(self):
        """User should be creatable without a password"""
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
            oauth_provider="google",
            oauth_id="google_123"
        )
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.email, "test@example.com")


class PasskeyModelTest(TestCase):
    def test_create_passkey_defaults(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        passkey = Passkey.objects.create(
            user=user,
            credential_id="cred_123",
            public_key="public-key",
            name="MacBook Pro",
        )

        self.assertEqual(passkey.sign_count, 0)
        self.assertIsNone(passkey.last_used_at)
        self.assertIn("MacBook Pro", str(passkey))

    def test_unique_credential_id_is_enforced(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        Passkey.objects.create(
            user=user,
            credential_id="cred_123",
            public_key="public-key",
            name="Device 1",
        )

        with self.assertRaises(IntegrityError):
            Passkey.objects.create(
                user=user,
                credential_id="cred_123",
                public_key="public-key-2",
                name="Device 2",
            )


class RestorationJobModelTest(TestCase):
    def test_create_restoration_job_defaults(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://example.com/original.jpg",
            expires_at=timezone.now() + timezone.timedelta(days=60),
        )

        self.assertEqual(job.status, "pending")
        self.assertFalse(job.is_unlocked)

    def test_missing_expires_at_is_invalid(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        job = RestorationJob(
            user=user,
            original_image_url="https://example.com/original.jpg",
        )

        with self.assertRaises(ValidationError):
            job.full_clean()

    def test_invalid_status_is_rejected(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        job = RestorationJob(
            user=user,
            original_image_url="https://example.com/original.jpg",
            status="unknown",
            expires_at=timezone.now() + timezone.timedelta(days=60),
        )

        with self.assertRaises(ValidationError):
            job.full_clean()

    def test_is_unlocked_true_when_unlocked_at_set(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://example.com/original.jpg",
            expires_at=timezone.now() + timezone.timedelta(days=60),
        )
        job.unlocked_at = timezone.now()
        job.save()

        self.assertTrue(job.is_unlocked)


class CreditModelsTest(TestCase):
    def test_create_credit_pack(self):
        pack = CreditPack.objects.create(
            sku="pack_5",
            credits=5,
            price_cents=999,
            active=True,
        )

        self.assertEqual(pack.credits, 5)
        self.assertTrue(pack.active)

    def test_credit_pack_unique_sku(self):
        CreditPack.objects.create(
            sku="pack_5",
            credits=5,
            price_cents=999,
            active=True,
        )

        with self.assertRaises(IntegrityError):
            CreditPack.objects.create(
                sku="pack_5",
                credits=10,
                price_cents=1499,
                active=True,
            )

    def test_credit_transaction_purchase(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        transaction = CreditTransaction.objects.create(
            user=user,
            amount=5,
            transaction_type="purchase",
            stripe_payment_id="pi_123",
        )

        self.assertEqual(transaction.amount, 5)
        self.assertEqual(transaction.transaction_type, "purchase")
        self.assertEqual(transaction.stripe_payment_id, "pi_123")

    def test_credit_transaction_unlock_with_job(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        job = RestorationJob.objects.create(
            user=user,
            original_image_url="https://example.com/original.jpg",
            expires_at=timezone.now() + timezone.timedelta(days=60),
        )
        transaction = CreditTransaction.objects.create(
            user=user,
            amount=-1,
            transaction_type="unlock",
            restoration_job=job,
        )

        self.assertEqual(transaction.amount, -1)
        self.assertEqual(transaction.restoration_job, job)

    def test_credit_transaction_unique_stripe_payment_id(self):
        user = User.objects.create(
            email="test@example.com",
            username="test@example.com",
        )
        CreditTransaction.objects.create(
            user=user,
            amount=5,
            transaction_type="purchase",
            stripe_payment_id="pi_123",
        )

        with self.assertRaises(IntegrityError):
            CreditTransaction.objects.create(
                user=user,
                amount=10,
                transaction_type="purchase",
                stripe_payment_id="pi_123",
            )
