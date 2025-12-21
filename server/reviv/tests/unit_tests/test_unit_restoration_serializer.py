from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from reviv.serializers.restoration import RestorationUploadSerializer


class RestorationUploadSerializerTest(SimpleTestCase):
    def _make_image_file(self, fmt: str, size=(600, 600)):
        buffer = BytesIO()
        image = Image.new("RGB", size, color="red")
        image.save(buffer, format=fmt)
        raw = buffer.getvalue()
        buffer.seek(0)
        return raw, SimpleUploadedFile(
            f"test.{fmt.lower()}",
            buffer.read(),
            content_type=f"image/{fmt.lower()}",
        )

    def test_invalid_format_is_rejected(self):
        _, upload = self._make_image_file("BMP")
        serializer = RestorationUploadSerializer(data={"image": upload})

        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors["image"][0],
            "Only JPG, PNG, WEBP formats allowed",
        )

    def test_invalid_image_bytes_are_rejected(self):
        upload = SimpleUploadedFile(
            "test.jpg",
            b"not-a-real-image",
            content_type="image/jpeg",
        )
        serializer = RestorationUploadSerializer(data={"image": upload})

        self.assertFalse(serializer.is_valid())
        self.assertEqual(serializer.errors["image"][0], "Invalid image file")

    def test_valid_image_resets_stream_position(self):
        raw, upload = self._make_image_file("JPEG")
        serializer = RestorationUploadSerializer(data={"image": upload})

        self.assertTrue(serializer.is_valid(), serializer.errors)
        validated = serializer.validated_data["image"]

        self.assertEqual(validated.read(), raw)
