from django.test import SimpleTestCase

from config import settings as project_settings


class DatabaseUrlParsingTest(SimpleTestCase):
    def test_sqlite_relative_url_uses_base_dir(self):
        result = project_settings._database_from_url("sqlite:///db.sqlite3")

        self.assertEqual(result["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(result["NAME"], project_settings.BASE_DIR / "db.sqlite3")
