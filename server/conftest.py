"""
Pytest bootstrap for running Django tests without pytest-django.

This project primarily uses Django's `TestCase` / `SimpleTestCase` classes.
When running tests via `pytest` directly, we must:
- set `DJANGO_SETTINGS_MODULE`
- call `django.setup()`
- create/teardown the Django test databases
"""

import os

import django
from django.test.utils import (
    setup_databases,
    setup_test_environment,
    teardown_databases,
    teardown_test_environment,
)


_db_cfg = None


def pytest_configure():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def pytest_sessionstart(session):
    global _db_cfg
    setup_test_environment()
    _db_cfg = setup_databases(verbosity=0, interactive=False, keepdb=False)


def pytest_sessionfinish(session, exitstatus):
    global _db_cfg
    if _db_cfg:
        teardown_databases(_db_cfg, verbosity=0)
        _db_cfg = None
    teardown_test_environment()


