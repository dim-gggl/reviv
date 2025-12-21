from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import cloudinary.uploader
import re
from reviv.models.restoration import RestorationJob
import logging

logger = logging.getLogger(__name__)


def extract_public_id(cloudinary_url):
    """Extract public_id from Cloudinary URL"""
    # URL format: https://res.cloudinary.com/{cloud_name}/image/{type}/{version}/{public_id}.{format}
    match = re.search(r'/([^/]+)/v\d+/(.+)\.\w+$', cloudinary_url)
    if match:
        return match.group(2)
    return None


@shared_task
def cleanup_expired_restorations():
    """
    Daily task to cleanup expired restoration jobs
    Deletes images from Cloudinary and database records
    """
    expired_jobs = RestorationJob.objects.filter(
        expires_at__lt=timezone.now()
    )

    count = 0
    for job in expired_jobs:
        try:
            # Delete from Cloudinary
            if job.original_image_url:
                public_id = extract_public_id(job.original_image_url)
                if public_id:
                    cloudinary.uploader.destroy(public_id)

            if job.restored_preview_url:
                public_id = extract_public_id(job.restored_preview_url)
                if public_id:
                    cloudinary.uploader.destroy(public_id)

            if job.restored_full_url:
                public_id = extract_public_id(job.restored_full_url)
                if public_id:
                    cloudinary.uploader.destroy(public_id, type='private')

            # Delete database record
            job.delete()
            count += 1

        except Exception as e:
            logger.error(f"Error cleaning up job {job.id}: {e}")

    logger.info(f"Cleaned up {count} expired restoration jobs")
    return count


@shared_task
def cleanup_failed_jobs():
    """
    Daily task to cleanup old failed jobs (>24 hours old)
    """
    cutoff_time = timezone.now() - timedelta(hours=24)
    failed_jobs = RestorationJob.objects.filter(
        status='failed',
        created_at__lt=cutoff_time
    )

    count = 0
    for job in failed_jobs:
        try:
            # Delete original image from Cloudinary if it was uploaded
            if job.original_image_url:
                public_id = extract_public_id(job.original_image_url)
                if public_id:
                    cloudinary.uploader.destroy(public_id)

            job.delete()
            count += 1

        except Exception as e:
            logger.error(f"Error cleaning up failed job {job.id}: {e}")

    logger.info(f"Cleaned up {count} failed jobs")
    return count