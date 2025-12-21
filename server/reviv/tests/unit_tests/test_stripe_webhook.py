from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
import stripe

from reviv.models import CreditTransaction, User


class StripeWebhookViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")

    @patch("reviv.views.payment.stripe.Webhook.construct_event")
    def test_webhook_adds_credits(self, mock_construct):
        mock_construct.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"user_id": str(self.user.id), "credits": "5"},
                    "payment_intent": "pi_123",
                }
            },
        }

        response = self.client.post(
            "/api/credits/webhook/",
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.credit_balance, Decimal("5.00"))
        self.assertEqual(CreditTransaction.objects.count(), 1)

    @patch("reviv.views.payment.stripe.Webhook.construct_event")
    def test_webhook_duplicate_payment_is_ignored(self, mock_construct):
        CreditTransaction.objects.create(
            user=self.user,
            amount=5,
            transaction_type="purchase",
            stripe_payment_id="pi_123",
        )
        mock_construct.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"user_id": str(self.user.id), "credits": "5"},
                    "payment_intent": "pi_123",
                }
            },
        }

        response = self.client.post(
            "/api/credits/webhook/",
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.credit_balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 1)

    @patch(
        "reviv.views.payment.stripe.Webhook.construct_event",
        side_effect=stripe.error.SignatureVerificationError("bad", "sig"),
    )
    def test_webhook_invalid_signature(self, _mock_construct):
        response = self.client.post(
            "/api/credits/webhook/",
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )

        self.assertEqual(response.status_code, 400)
