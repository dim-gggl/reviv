from django.test import TestCase
from rest_framework.test import APIClient


class BrowsableApiCssTest(TestCase):
    def test_api_root_browsable_includes_rest_framework_css(self):
        """
        Ensure the DRF browsable API loads its CSS via an absolute /static/ URL.
        """
        client = APIClient()
        response = client.get("/api/", HTTP_ACCEPT="text/html")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn('href="/static/rest_framework/css/', content)
        self.assertIn("/api/health/", content)


