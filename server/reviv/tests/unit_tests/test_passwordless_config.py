from django.test import TestCase
from django.conf import settings


class PasswordlessConfigTest(TestCase):
    def test_only_google_oauth_provider_installed(self):
        """Only Google OAuth provider should be in INSTALLED_APPS"""
        installed_apps = settings.INSTALLED_APPS
        self.assertIn("allauth.socialaccount.providers.google", installed_apps)
        self.assertNotIn("allauth.socialaccount.providers.apple", installed_apps)
        self.assertNotIn("allauth.socialaccount.providers.facebook", installed_apps)
        self.assertNotIn("allauth.socialaccount.providers.microsoft", installed_apps)

    def test_account_login_methods_email_only(self):
        """Account login method should be email only (current non-deprecated setting)"""
        self.assertEqual(settings.ACCOUNT_LOGIN_METHODS, {"email"})

    def test_account_signup_fields_no_username(self):
        """Signup fields should not include username (email only for passwordless)"""
        self.assertIn("email*", settings.ACCOUNT_SIGNUP_FIELDS)
        # For passwordless, we should not have password fields
        self.assertNotIn("password1*", settings.ACCOUNT_SIGNUP_FIELDS)
        self.assertNotIn("password2*", settings.ACCOUNT_SIGNUP_FIELDS)

    def test_password_validators_empty(self):
        """Password validators should be empty (no passwords used)"""
        self.assertEqual(settings.AUTH_PASSWORD_VALIDATORS, [])
