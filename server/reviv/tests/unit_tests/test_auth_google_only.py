from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status


class GoogleOnlyOAuthTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_oauth_initiate_google_allowed(self):
        """Google OAuth should be allowed"""
        response = self.client.post(
            "/api/auth/oauth/initiate/",
            {"provider": "google"},
            format="json"
        )
        # Google should pass validation (not rejected with INVALID_PROVIDER)
        # May fail with PROVIDER_NOT_CONFIGURED in test env, which is acceptable
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            error_code = response.data.get("error", {}).get("code")
            self.assertNotEqual(error_code, "INVALID_PROVIDER",
                "Google should not be rejected as invalid provider")

    def test_oauth_initiate_facebook_rejected(self):
        """Facebook OAuth should be rejected"""
        response = self.client.post(
            "/api/auth/oauth/initiate/",
            {"provider": "facebook"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "INVALID_PROVIDER")

    def test_oauth_initiate_apple_rejected(self):
        """Apple OAuth should be rejected"""
        response = self.client.post(
            "/api/auth/oauth/initiate/",
            {"provider": "apple"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "INVALID_PROVIDER")

    def test_oauth_initiate_microsoft_rejected(self):
        """Microsoft OAuth should be rejected"""
        response = self.client.post(
            "/api/auth/oauth/initiate/",
            {"provider": "microsoft"},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "INVALID_PROVIDER")
