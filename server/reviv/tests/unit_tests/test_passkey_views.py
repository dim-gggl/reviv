from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from fido2 import cbor

from reviv.models import Passkey, User


class PasskeyRegistrationViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        self.client.force_authenticate(user=self.user)

    @patch("reviv.views.passkey.server")
    def test_begin_passkey_registration(self, mock_server):
        registration_options = {
            "challenge": b"challenge",
            "rp": {"name": "reviv.pics"},
            "user": {
                "id": b"user-id",
                "name": "test@example.com",
                "displayName": "test@example.com",
            },
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "timeout": 60000,
            "attestation": "none",
            "authenticatorSelection": {},
        }
        mock_server.register_begin.return_value = (cbor.encode(registration_options), b"state")

        response = self.client.post("/api/auth/passkey/register/begin/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["challenge"], list(b"challenge"))
        self.assertEqual(response.data["challenge_b64"], "Y2hhbGxlbmdl")
        self.assertIn("rp", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["id"], list(b"user-id"))
        self.assertEqual(response.data["user"]["id_b64"], "dXNlci1pZA==")

    def test_register_complete_without_state(self):
        response = self.client.post(
            "/api/auth/passkey/register/complete/",
            {"credential": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class PasskeyLoginViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="test@example.com", username="test@example.com")
        Passkey.objects.create(
            user=self.user,
            credential_id="cred_id",
            public_key="public_key",
            sign_count=0,
            name="Device",
        )

    @patch("reviv.views.passkey.server")
    def test_begin_passkey_login(self, mock_server):
        auth_options = {
            "challenge": b"challenge",
            "allowCredentials": [{"type": "public-key", "id": b"cred_id"}],
            "rpId": "localhost",
            "timeout": 60000,
            "userVerification": "preferred",
        }
        mock_server.authenticate_begin.return_value = (cbor.encode(auth_options), b"state")

        response = self.client.post("/api/auth/passkey/login/begin/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["challenge"], list(b"challenge"))
        self.assertEqual(response.data["challenge_b64"], "Y2hhbGxlbmdl")
        self.assertEqual(response.data["allowCredentials"][0]["id"], list(b"cred_id"))
        self.assertEqual(response.data["allowCredentials"][0]["id_b64"], "Y3JlZF9pZA==")

    def test_login_complete_without_state(self):
        response = self.client.post(
            "/api/auth/passkey/login/complete/",
            {"credential": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
