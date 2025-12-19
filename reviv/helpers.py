import os
import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


def upload_image_to_s3(file_obj, *, object_name: str | None = None) -> str:
    """
    Upload a Django UploadedFile/file-like object to S3 and return the object key.

    NOTE: Prefer using django-storages as the Django DEFAULT_FILE_STORAGE. This helper 
    is optional and only used for local development.
    """
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None) or os.getenv(
        "AWS_STORAGE_BUCKET_NAME", ""
    )
    if not bucket:
        raise RuntimeError("AWS_STORAGE_BUCKET_NAME is not configured.")

    key = object_name or os.path.basename(getattr(file_obj, "name", "upload.bin"))
    client = boto3.client("s3")
    try:
        # upload_fileobj expects a file-like object (not a filesystem path).
        client.upload_fileobj(file_obj, bucket, key)
    except ClientError as exc:
        logger.exception("S3 upload failed: %s", exc)
        raise
    return key


def get_public_url(object_name: str) -> str:
    """
    Build a public S3 URL for an object.

    This assumes the object is publicly accessible, or that you use presigned URLs elsewhere.
    """
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None) or os.getenv(
        "AWS_STORAGE_BUCKET_NAME", ""
    )
    region = getattr(settings, "AWS_S3_REGION_NAME", None) or os.getenv("AWS_S3_REGION_NAME", "")
    if not bucket or not region:
        raise RuntimeError("AWS_STORAGE_BUCKET_NAME / AWS_S3_REGION_NAME are not configured.")
    return f"https://{bucket}.s3.{region}.amazonaws.com/{object_name}"