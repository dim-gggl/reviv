from celery import shared_task
import cloudinary.uploader
import requests
from io import BytesIO
from PIL import Image
from reviv.models.restoration import RestorationJob
from reviv.utils import kie_client
import logging

logger = logging.getLogger(__name__)

# Restoration prompt from const.py
RESTORATION_PROMPT = """
Restore this old printed photo to brand new condition.
Remove all scratches, fading, dust, spots, noise, and any
yellow/brown aging cast. Remove all light reflections,
flash glare, glossy shine, and moiré patterns since this
is a picture taken of a physical print. Correct any blur,
softness, or out-of-focus areas caused by the paper being
curved or poor photographing angle — make the entire image
uniformly sharp from corner to corner. Sharpen details gently
and naturally, enhance contrast, and upscale to high resolution.
If the photo is black-and-white, restore clean neutral tones
with deep blacks, bright whites, and rich grayscale — keep it
strictly monochrome, no colorization. If the photo is originally
in color, bring back accurate, vibrant yet natural original colors
without over-saturation. Preserve the authentic vintage feel of the
era, nothing overly modern or artificial.
"""


@shared_task(bind=True, max_retries=3)
def process_restoration(self, job_id):
    """
    Process an image restoration job asynchronously

    Steps:
    1. Update status to 'processing'
    2. Create kie.ai task
    3. Wait for completion
    4. Download restored image
    5. Upload watermarked preview to Cloudinary
    6. Upload full version to Cloudinary (private)
    7. Update job with URLs and mark completed
    """
    try:
        job = RestorationJob.objects.get(id=job_id)
    except RestorationJob.DoesNotExist:
        logger.error(f"RestorationJob {job_id} not found")
        return

    try:
        # Update status
        job.status = 'processing'
        job.save()

        # Create kie.ai task
        logger.info(f"Creating kie.ai task for job {job_id}")
        task_data = kie_client.create_task(
            image_url=job.original_image_url,
            prompt=RESTORATION_PROMPT
        )
        job.kie_task_id = task_data['taskId']
        job.save()

        # Wait for completion (max 10 minutes)
        logger.info(f"Waiting for kie.ai task {task_data['taskId']}")
        result = kie_client.wait_for_completion(task_data['taskId'], max_wait_seconds=600)

        if result['state'] == 'success':
            # Download restored image
            restored_url = result['output'][0]
            response = requests.get(restored_url, timeout=30)
            response.raise_for_status()
            image_data = BytesIO(response.content)

            # Upload watermarked preview to Cloudinary
            logger.info(f"Uploading watermarked preview for job {job_id}")
            preview_upload = cloudinary.uploader.upload(
                image_data,
                folder='reviv/previews',
                transformation=[
                    {'overlay': 'reviv_logo', 'opacity': 30, 'flags': 'tiled'}
                ],
                format='jpg',
                quality='auto:good'
            )
            job.restored_preview_url = preview_upload['secure_url']

            # Reset image data position
            image_data.seek(0)

            # Upload full resolution (private)
            logger.info(f"Uploading full resolution for job {job_id}")
            full_upload = cloudinary.uploader.upload(
                image_data,
                folder='reviv/full',
                type='private',
                format='png',
                quality='auto:best'
            )
            job.restored_full_url = full_upload['secure_url']

            # Mark completed
            job.status = 'completed'
            job.save()

            logger.info(f"Job {job_id} completed successfully")
        else:
            # kie.ai processing failed
            job.status = 'failed'
            job.save()
            logger.error(f"kie.ai processing failed for job {job_id}: {result}")

    except TimeoutError:
        job.status = 'failed'
        job.save()
        logger.error(f"Job {job_id} timed out after 10 minutes")

    except Exception as exc:
        job.status = 'failed'
        job.save()
        logger.exception(f"Error processing job {job_id}: {exc}")
        raise self.retry(exc=exc, countdown=60)  # Retry after 1 minute