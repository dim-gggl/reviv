import sys

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import connections


class RevivConfig(AppConfig):
    name = "reviv"

    def ready(self) -> None:
        @register(Tags.database)
        def _check_allauth_mfa_migrations(app_configs, **kwargs):
            """
            Prevent a confusing runtime 500 when allauth MFA is enabled but migrations were not applied.
            """
            if "allauth.mfa" not in settings.INSTALLED_APPS:
                return []

            # Allow database-related management commands to run even if tables are not present yet.
            if any(cmd in sys.argv for cmd in {"migrate", "makemigrations", "showmigrations"}):
                return []

            try:
                tables = connections["default"].introspection.table_names()
            except Exception:
                # If the database is not available yet, do not block startup here.
                return []

            if "mfa_authenticator" not in tables:
                issue_cls = Warning
                if "runserver" in sys.argv:
                    issue_cls = Error
                issue_id = "reviv.W001"
                if issue_cls is Error:
                    issue_id = "reviv.E001"
                return [
                    issue_cls(
                        "Allauth MFA is enabled, but its database tables are missing.",
                        hint="Run: uv run python manage.py migrate",
                        id=issue_id,
                    )
                ]

            return []
