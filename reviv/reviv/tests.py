import io

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .services import ImageEnhancementService


class ReplicateOutputNormalizationTests(TestCase):
    def test_iterator_of_bytes_chunks_is_concatenated(self):
        """
        Replicate integrations can return an iterator of bytes chunks (streaming).
        We must concatenate all chunks; taking only the first chunk would truncate the PNG.
        """
        test_image = Image.new("RGB", (32, 32), color="red")
        buffer = io.BytesIO()
        test_image.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()

        chunks = [png_bytes[:17], png_bytes[17:]]
        image_content, output_url = ImageEnhancementService._extract_image_content_and_url(iter(chunks))

        self.assertIsNone(output_url)
        self.assertEqual(image_content, png_bytes)


class AccessControlTests(TestCase):
    def test_home_anonymous_shows_demo_slider_only(self):
        """
        Unauthenticated users should only see the demo before/after slider.
        The upload UI must not be present.
        """
        response = self.client.get(reverse("reviv:home"))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'id="imageCompare"')
        self.assertContains(response, "reviv/demo/before.jpg")
        self.assertContains(response, "reviv/demo/after.png")

        self.assertNotContains(response, "Drop Image Here")
        self.assertNotContains(response, 'id="fileInput"')

    def test_gallery_requires_login(self):
        response = self.client.get(reverse("reviv:gallery"))
        self.assertEqual(response.status_code, 302)

        login_url = reverse("account_login")
        self.assertTrue(response["Location"].startswith(login_url))

    def test_upload_requires_login_returns_json_401(self):
        response = self.client.post(reverse("reviv:upload"))
        self.assertEqual(response.status_code, 401)
