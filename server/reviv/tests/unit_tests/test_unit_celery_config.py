from django.test import SimpleTestCase
from celery import Celery

import config


class CeleryConfigTest(SimpleTestCase):
    def test_celery_app_is_exposed(self):
        self.assertTrue(hasattr(config, "celery_app"))
        self.assertIsInstance(config.celery_app, Celery)
