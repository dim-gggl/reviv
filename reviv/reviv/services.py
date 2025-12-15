import os
import io
import replicate
import requests
from PIL import Image
from dotenv import load_dotenv
from django.core.files.base import ContentFile
from .models import PhotoRestoration

load_dotenv()


class ImageEnhancementService:
    """Service for enhancing images using nano banana API"""

    @staticmethod
    def _extract_image_content_and_url(output):
        """
        Normalize Replicate output into (image_content_bytes, output_url).

        Replicate outputs can be:
        - a file-like object with .read() (and sometimes .url)
        - a URL string
        - raw bytes
        - a list/iterator of any of the above
        - an iterator of bytes chunks (streaming), which must be concatenated

        The previous implementation incorrectly took only the first item from an iterable,
        which can produce truncated PNG files when the iterable contains byte chunks.
        """
        image_content = None
        output_url = None

        # Concrete containers: keep first item unless it is bytes chunks.
        if isinstance(output, (list, tuple)):
            if not output:
                raise Exception("Empty output received from Replicate")
            if all(isinstance(x, (bytes, bytearray)) for x in output):
                return b"".join(bytes(x) for x in output), None
            output = output[0]

        # Iterators/generators: consume to detect bytes chunks vs first output item.
        if hasattr(output, "__iter__") and not isinstance(output, (str, bytes, bytearray)):
            try:
                items = list(output)
            except TypeError:
                items = None

            if items is not None:
                if not items:
                    raise Exception("Empty iterable output received from Replicate")
                if all(isinstance(x, (bytes, bytearray)) for x in items):
                    return b"".join(bytes(x) for x in items), None
                output = items[0]

        # Raw bytes
        if isinstance(output, (bytes, bytearray)):
            return bytes(output), None

        # URL string
        if isinstance(output, str):
            return None, output

        # File-like output
        if hasattr(output, "read"):
            image_content = output.read()
            if hasattr(output, "url"):
                output_url = output.url
            return image_content, output_url

        # Object with a url attribute
        if hasattr(output, "url"):
            return None, output.url

        raise Exception(f"Unexpected output type: {type(output)}")

    @staticmethod
    def _download_image(url: str) -> bytes:
        """Download image bytes from a URL."""
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content

    @staticmethod
    def _validate_and_reencode_png(image_content: bytes) -> bytes:
        """
        Fully decode the image and re-encode it as a valid PNG.

        Fully decoding via image.load() ensures we fail on truncated/corrupt sources
        instead of producing partially readable outputs.
        """
        image = Image.open(io.BytesIO(image_content))
        image.load()

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")

        png_buffer = io.BytesIO()
        image.save(png_buffer, format="PNG", optimize=True)
        return png_buffer.getvalue()

    @staticmethod
    def enhance_image(restoration: PhotoRestoration, prompt: str = None):
        """
        Enhance an image using the Replicate nano banana API

        Args:
            restoration: PhotoRestoration instance
            prompt: Custom prompt for enhancement (optional)

        Returns:
            The URL of the enhanced image
        """
        from .const import PROMPT as DEFAULT_PROMPT

        if not prompt:
            prompt = DEFAULT_PROMPT

        try:
            restoration.status = 'processing'
            restoration.save()

            # Get the file path
            image_path = restoration.original_image.path

            # Read the image fully into memory so it remains available if Replicate reads asynchronously.
            with open(image_path, "rb") as image_file:
                image_data = image_file.read()

            image_file_obj = io.BytesIO(image_data)
            # Some clients infer MIME type from the file name/extension.
            # Adding a name avoids "application/octet-stream" uploads for in-memory buffers.
            image_file_obj.name = os.path.basename(image_path)
            image_file_obj.seek(0)

            output = replicate.run(
                "google/nano-banana-pro",
                input={
                    "prompt": prompt,
                    "resolution": "2K",
                    "image_input": [image_file_obj],
                    "aspect_ratio": "match_input_image",
                    "output_format": "png",
                    "safety_filter_level": "block_only_high"
                }
            )

            image_content, output_url = ImageEnhancementService._extract_image_content_and_url(output)
            if output_url and not image_content:
                image_content = ImageEnhancementService._download_image(output_url)
            if not image_content:
                raise Exception("Failed to retrieve image content")

            png_content = ImageEnhancementService._validate_and_reencode_png(image_content)

            # Save via Django storage to avoid partial/truncated writes.
            restoration.enhanced_image.save(
                f"enhanced_{restoration.id}.png",
                ContentFile(png_content),
                save=False,
            )

            restoration.status = 'completed'
            restoration.save()

            return output_url if output_url else restoration.enhanced_image.url

        except Exception as e:
            restoration.status = 'failed'
            restoration.error_message = str(e)
            restoration.save()
            raise
