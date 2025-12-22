from django.core.cache import cache
from django.test import SimpleTestCase

from reviv import utils
from reviv.utils.webauthn import webauthn_pop_state, webauthn_store_state


class UtilsExportsTest(SimpleTestCase):
    def test_social_share_error_is_exported(self):
        self.assertIn("SocialShareAlreadyUsedError", utils.__all__)
        self.assertTrue(hasattr(utils, "SocialShareAlreadyUsedError"))


class WebAuthnStateTest(SimpleTestCase):
    def test_webauthn_state_roundtrip(self):
        cache.clear()
        payload = {"user_id": 123, "state": b"state-bytes"}

        nonce = webauthn_store_state("register", payload, ttl_seconds=60)
        loaded = webauthn_pop_state("register", nonce)

        self.assertEqual(loaded["user_id"], 123)
        self.assertEqual(loaded["state"], b"state-bytes")
        self.assertIsNone(webauthn_pop_state("register", nonce))
