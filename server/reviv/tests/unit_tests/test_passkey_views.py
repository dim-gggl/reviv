from unittest.mock import Mock, patch

from django.core.cache import cache
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

    @patch("reviv.views.passkey.webauthn_store_state")
    @patch("reviv.views.passkey.server")
    def test_begin_passkey_registration_returns_registration_id(self, mock_server, mock_store_state):
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
        mock_store_state.return_value = "reg_nonce"

        response = self.client.post("/api/auth/passkey/register/begin/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["registration_id"], "reg_nonce")

    def test_register_complete_without_state(self):
        response = self.client.post(
            "/api/auth/passkey/register/complete/",
            {"credential": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    @patch("reviv.views.passkey.webauthn_pop_state")
    @patch("reviv.views.passkey.server")
    def test_register_complete_uses_cached_state(self, mock_server, mock_pop_state):
        mock_pop_state.return_value = {"user_id": self.user.id, "state": b"state"}
        mock_server.register_complete.return_value = Mock(
            credential_id=b"cred",
            public_key={"kty": "EC"},
            sign_count=1,
        )

        response = self.client.post(
            "/api/auth/passkey/register/complete/",
            {
                "registration_id": "reg_nonce",
                "credential": {
                    "clientDataJSON": [1, 2, 3],
                    "attestationObject": [4, 5, 6],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Passkey.objects.filter(user=self.user).exists())


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

    @patch("reviv.views.passkey.webauthn_store_state")
    @patch("reviv.views.passkey.server")
    def test_begin_passkey_login_returns_authentication_id(self, mock_server, mock_store_state):
        auth_options = {
            "challenge": b"challenge",
            "allowCredentials": [{"type": "public-key", "id": b"cred_id"}],
            "rpId": "localhost",
            "timeout": 60000,
            "userVerification": "preferred",
        }
        mock_server.authenticate_begin.return_value = (cbor.encode(auth_options), b"state")
        mock_store_state.return_value = "auth_nonce"

        response = self.client.post("/api/auth/passkey/login/begin/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["authentication_id"], "auth_nonce")

    def test_login_complete_without_state(self):
        response = self.client.post(
            "/api/auth/passkey/login/complete/",
            {"credential": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    @patch("reviv.views.passkey._build_attested_credential")
    @patch("reviv.views.passkey.webauthn_pop_state")
    @patch("reviv.views.passkey.server")
    def test_login_complete_rejects_replay(self, mock_server, mock_pop_state, mock_build_credential):
        mock_pop_state.return_value = {"state": {"challenge": "challenge", "user_verification": None}}
        mock_server.authenticate_complete.return_value = Mock()
        mock_build_credential.return_value = Mock()

        passkey = Passkey.objects.create(
            user=self.user,
            credential_id="Y3JlZA==",
            public_key="o2N0eXB4IA==",
            sign_count=2,
            name="Device",
        )

        auth_data = b"\x00" * 32 + b"\x01" + (1).to_bytes(4, "big")
        response = self.client.post(
            "/api/auth/passkey/login/complete/",
            {
                "authentication_id": "auth_nonce",
                "credential": {
                    "id": passkey.credential_id,
                    "clientDataJSON": [1],
                    "authenticatorData": list(auth_data),
                    "signature": [3],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "REPLAY_DETECTED")

    @patch("reviv.views.passkey.server")
    def test_passkey_login_begin_rate_limited(self, mock_server):
        auth_options = {
            "challenge": b"challenge",
            "allowCredentials": [{"type": "public-key", "id": b"cred_id"}],
            "rpId": "localhost",
            "timeout": 60000,
            "userVerification": "preferred",
        }
        mock_server.authenticate_begin.return_value = (cbor.encode(auth_options), b"state")
        cache.clear()
        for _ in range(11):
            response = self.client.post("/api/auth/passkey/login/begin/")
        self.assertIn(response.status_code, {403, 429})
