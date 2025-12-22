from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from fido2 import cbor

from reviv.models import Passkey, User


class EmailPasskeyRegistrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("reviv.views.email_passkey.server")
    def test_email_passkey_register_begin_unauthenticated(self, mock_server):
        """Should allow unauthenticated users to start passkey registration with email"""
        registration_options = {
            "challenge": b"challenge",
            "rp": {"name": "reviv.pics"},
            "user": {
                "id": b"user-id",
                "name": "newuser@example.com",
                "displayName": "newuser@example.com",
            },
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "timeout": 60000,
            "attestation": "none",
            "authenticatorSelection": {},
        }
        mock_server.register_begin.return_value = (cbor.encode(registration_options), b"state")

        response = self.client.post(
            "/api/auth/email-passkey/register/begin/",
            {"email": "newuser@example.com"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["challenge"], list(b"challenge"))
        self.assertEqual(response.data["challenge_b64"], "Y2hhbGxlbmdl")
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["id"], list(b"user-id"))
        self.assertEqual(response.data["user"]["id_b64"], "dXNlci1pZA==")

    def test_email_passkey_register_begin_missing_email(self):
        """Should return error when email is missing"""
        response = self.client.post(
            "/api/auth/email-passkey/register/begin/",
            {},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("reviv.views.email_passkey.server")
    def test_email_passkey_register_begin_creates_user(self, mock_server):
        """Should create user if email doesn't exist"""
        registration_options = {
            "challenge": b"challenge",
            "rp": {"name": "reviv.pics"},
            "user": {
                "id": b"user-id",
                "name": "newuser@example.com",
                "displayName": "newuser@example.com",
            },
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "timeout": 60000,
            "attestation": "none",
            "authenticatorSelection": {},
        }
        mock_server.register_begin.return_value = (cbor.encode(registration_options), b"state")

        email = "newuser@example.com"
        self.assertFalse(User.objects.filter(email=email).exists())

        response = self.client.post(
            "/api/auth/email-passkey/register/begin/",
            {"email": email},
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(User.objects.filter(email=email).exists())
        user = User.objects.get(email=email)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(response.data["challenge"], list(b"challenge"))
        self.assertEqual(response.data["challenge_b64"], "Y2hhbGxlbmdl")

    def test_email_passkey_register_begin_invalid_email(self):
        """Should reject invalid email format"""
        response = self.client.post(
            "/api/auth/email-passkey/register/begin/",
            {"email": "not-an-email"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "INVALID_EMAIL")

    def test_email_passkey_register_begin_oauth_user_rejected(self):
        """Should reject registration for users with OAuth provider"""
        # Create an OAuth user
        User.objects.create(
            email="oauth@example.com",
            username="oauth@example.com",
            oauth_provider="google",
            oauth_id="google_123"
        )

        response = self.client.post(
            "/api/auth/email-passkey/register/begin/",
            {"email": "oauth@example.com"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "OAUTH_USER_EXISTS")

    @patch("reviv.views.email_passkey.webauthn_pop_state")
    @patch("reviv.views.email_passkey.server")
    def test_email_passkey_register_complete_creates_passkey(self, mock_server, mock_pop_state):
        user = User.objects.create(email="new@example.com", username="new@example.com")
        mock_pop_state.return_value = {"user_id": user.id, "state": b"state"}
        mock_server.register_complete.return_value = Mock(
            credential_id=b"cred",
            public_key={"kty": "EC"},
            sign_count=1,
        )

        response = self.client.post(
            "/api/auth/email-passkey/register/complete/",
            {
                "registration_id": "reg_nonce",
                "credential": {
                    "clientDataJSON": [1],
                    "attestationObject": [2],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(Passkey.objects.filter(user=user).exists())
