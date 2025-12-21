from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import Mock, patch

from reviv.models import CreditPack, CreditTransaction, User


class CreditPackListViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        self.client.force_authenticate(user=self.user)

        CreditPack.objects.create(sku="pack_5", credits=5, price_cents=999, active=True)
        CreditPack.objects.create(sku="pack_10", credits=10, price_cents=1499, active=True)
        CreditPack.objects.create(sku="pack_inactive", credits=3, price_cents=499, active=False)

    def test_list_credit_packs(self):
        response = self.client.get("/api/credits/packs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["sku"], "pack_5")
        self.assertEqual(response.data[1]["sku"], "pack_10")


class CreditTransactionViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        self.other_user = User.objects.create(email="other@example.com", username="other@example.com")
        self.client.force_authenticate(user=self.user)

        CreditTransaction.objects.create(
            user=self.user,
            amount=5,
            transaction_type="purchase",
            stripe_payment_id="pi_123",
        )
        CreditTransaction.objects.create(
            user=self.other_user,
            amount=5,
            transaction_type="purchase",
            stripe_payment_id="pi_456",
        )

    def test_list_transactions(self):
        response = self.client.get("/api/credits/transactions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["amount"], 5)


class StripeCheckoutViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        self.client.force_authenticate(user=self.user)
        self.pack = CreditPack.objects.create(
            sku="pack_5",
            credits=5,
            price_cents=999,
            active=True,
        )

    @patch("reviv.views.payment.stripe.checkout.Session.create")
    def test_create_checkout_session(self, mock_create):
        mock_create.return_value = Mock(url="https://checkout.stripe.com/session123")

        response = self.client.post("/api/credits/purchase/", {"sku": "pack_5"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["checkout_url"], "https://checkout.stripe.com/session123")
        mock_create.assert_called_once()

    def test_create_checkout_session_invalid_sku(self):
        response = self.client.post("/api/credits/purchase/", {"sku": "invalid"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
        self.assertIn("code", response.data["error"])
