from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from reviv.models import User


class AuthIntegrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_jwt_authentication(self):
        user = User.objects.create(email="test@example.com", username="test@example.com")
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "test@example.com")

    def test_unauthorized_access(self):
        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 401)
