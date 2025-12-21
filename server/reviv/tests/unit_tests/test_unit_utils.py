from django.test import SimpleTestCase

from reviv import utils


class UtilsExportsTest(SimpleTestCase):
    def test_social_share_error_is_exported(self):
        self.assertIn("SocialShareAlreadyUsedError", utils.__all__)
        self.assertTrue(hasattr(utils, "SocialShareAlreadyUsedError"))
