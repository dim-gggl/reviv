from unittest.mock import Mock, patch

from django.test import TestCase
from django.test import override_settings
from rest_framework.test import APIClient


class HealthCheckViewTest(TestCase):
    @override_settings(CELERY_BROKER_URL="redis://localhost:6379/0")
    @patch("reviv.views.health.cache")
    @patch("reviv.views.health.connection.ensure_connection")
    @patch("reviv.views.health.current_app")
    def test_health_check_healthy(self, mock_current_app, _mock_db, mock_cache):
        mock_cache.set.return_value = True
        mock_cache.get.return_value = "ok"
        inspector = Mock()
        inspector.stats.return_value = {"worker": {}}
        mock_current_app.control.inspect.return_value = inspector

        client = APIClient()
        response = client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "healthy")

    @override_settings(CELERY_BROKER_URL="")
    @patch("reviv.views.health.cache")
    @patch("reviv.views.health.connection.ensure_connection")
    def test_health_check_celery_not_configured(self, _mock_db, mock_cache):
        mock_cache.set.return_value = True
        mock_cache.get.return_value = "ok"

        client = APIClient()
        response = client.get("/api/health/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["status"], "degraded")
        self.assertEqual(response.data["checks"]["celery"], "not configured")
