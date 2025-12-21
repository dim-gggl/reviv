from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

import cloudinary.uploader
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from reviv.models import CreditTransaction, RestorationJob
from reviv.serializers import RestorationJobSerializer, RestorationUploadSerializer
from reviv.tasks import process_restoration
from reviv.tasks.cleanup import extract_public_id
from reviv.utils import format_error

User = get_user_model()

SOCIAL_SHARE_SIGNING_SALT = "reviv.social_share_unlock"
SOCIAL_SHARE_STATE_TTL_SECONDS = 10 * 60
SOCIAL_SHARE_CONFIRM_MIN_DELAY_SECONDS = 0


def _social_share_state_cache_key(user_id: int, job_id: int) -> str:
    return f"social_share:{user_id}:{job_id}"


def _make_social_share_token(user_id: int, job_id: int) -> str:
    return signing.dumps({"u": user_id, "j": job_id}, salt=SOCIAL_SHARE_SIGNING_SALT)


def _read_social_share_token(token: str) -> dict:
    return signing.loads(
        token,
        max_age=SOCIAL_SHARE_STATE_TTL_SECONDS,
        salt=SOCIAL_SHARE_SIGNING_SALT,
    )


def _build_share_redirect_urls(request, job_id: int, token: str) -> dict:
    urls = {}
    for platform in ["facebook", "twitter", "linkedin", "pinterest"]:
        path = f"/api/restorations/{job_id}/share-redirect/{platform}/?s={token}"
        urls[platform] = request.build_absolute_uri(path)
    return urls


def _build_share_payload(user_id: int):
    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
    referral_url = f"{frontend_url}?ref={user_id}"
    message = (
        "I just restored this old photo with reviv.pics! "
        f"Try it free: {referral_url}"
    )
    encoded_url = quote(referral_url, safe="")
    encoded_text = quote(message, safe="")

    return {
        "facebook": f"https://facebook.com/sharer.php?u={encoded_url}",
        "twitter": f"https://twitter.com/intent/tweet?text={encoded_text}",
        "linkedin": f"https://linkedin.com/sharing/share-offsite/?url={encoded_url}",
        "pinterest": f"https://pinterest.com/pin/create/button/?url={encoded_url}",
        "instagram": {
            "type": "manual",
            "caption": message,
            "deep_link": "instagram://app",
        },
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_image(request):
    """
    Upload an image for restoration.
    """
    active_jobs_count = RestorationJob.objects.filter(
        user=request.user,
        expires_at__gt=timezone.now(),
    ).count()

    if active_jobs_count >= 6:
        return Response(
            format_error(
                code="history_limit",
                message="Maximum 6 images. Delete or unlock one to continue",
                details={"max_jobs": 6},
            ),
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = RestorationUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            format_error(
                code="validation_error",
                message="Invalid upload",
                details=serializer.errors,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    image = serializer.validated_data["image"]

    try:
        upload_result = cloudinary.uploader.upload(
            image,
            folder="reviv/originals",
            format="jpg",
            quality="auto:best",
        )
    except Exception:
        return Response(
            format_error(
                code="upload_failed",
                message="Failed to upload image",
            ),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    job = RestorationJob.objects.create(
        user=request.user,
        original_image_url=upload_result["secure_url"],
        status="pending",
        expires_at=timezone.now() + timedelta(days=60),
    )

    process_restoration.delay(job.id)

    return Response(
        {"job_id": job.id, "status": job.status},
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def restoration_status(request, job_id):
    """
    Get restoration job status.
    """
    try:
        job = RestorationJob.objects.get(id=job_id, user=request.user)
    except RestorationJob.DoesNotExist:
        return Response(
            format_error(code="not_found", message="Job not found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    data = {
        "job_id": job.id,
        "status": job.status,
        "preview_url": job.restored_preview_url if job.status == "completed" else None,
        "error": "Restoration failed" if job.status == "failed" else None,
    }

    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def restoration_history(request):
    """
    Get user's restoration history.
    """
    jobs = RestorationJob.objects.filter(
        user=request.user,
        expires_at__gt=timezone.now(),
    )[:6]

    serializer = RestorationJobSerializer(jobs, many=True)
    return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_restoration(request, job_id):
    """
    Delete a restoration job.
    """
    try:
        job = RestorationJob.objects.get(id=job_id, user=request.user)
    except RestorationJob.DoesNotExist:
        return Response(
            format_error(code="not_found", message="Job not found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
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
                cloudinary.uploader.destroy(public_id, type="private")
    except Exception:
        pass

    job.delete()
    return Response({"message": "Job deleted successfully", "status": "ok"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def unlock_restoration(request, job_id):
    """
    Unlock a restoration using credits.
    """
    try:
        job = RestorationJob.objects.get(id=job_id, user=request.user)
    except RestorationJob.DoesNotExist:
        return Response(
            format_error(code="not_found", message="Job not found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if job.status != "completed":
        return Response(
            format_error(
                code="invalid_state",
                message="Restoration not completed",
                details={"status": job.status},
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if job.unlocked_at:
        return Response(
            format_error(code="already_unlocked", message="Already unlocked"),
            status=status.HTTP_409_CONFLICT,
        )

    with transaction.atomic():
        user = User.objects.select_for_update().get(id=request.user.id)
        if user.credit_balance < Decimal("1.00"):
            return Response(
                format_error(
                    code="insufficient_credits",
                    message="Insufficient credits",
                    details={"credits_available": str(user.credit_balance)},
                ),
                status=status.HTTP_403_FORBIDDEN,
            )

        user.credit_balance = user.credit_balance - Decimal("1.00")
        user.save(update_fields=["credit_balance"])

        CreditTransaction.objects.create(
            user=user,
            amount=-1,
            transaction_type="unlock",
            restoration_job=job,
        )

        job.unlock_method = "paid"
        job.unlocked_at = timezone.now()
        job.save(update_fields=["unlock_method", "unlocked_at"])

    return Response(
        {
            "full_image_url": job.restored_full_url,
            "credits_remaining": str(user.credit_balance),
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def share_unlock(request, job_id):
    """
    Start social share unlock flow.
    """
    try:
        job = RestorationJob.objects.get(id=job_id, user=request.user)
    except RestorationJob.DoesNotExist:
        return Response(
            format_error(code="not_found", message="Job not found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if job.status != "completed":
        return Response(
            format_error(
                code="invalid_state",
                message="Restoration not completed",
                details={"status": job.status},
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if job.unlocked_at:
        return Response(
            format_error(code="already_unlocked", message="Already unlocked"),
            status=status.HTTP_409_CONFLICT,
        )

    if request.user.social_share_unlock_used:
        return Response(
            format_error(
                code="social_share_used",
                message="Social share unlock already used",
            ),
            status=status.HTTP_403_FORBIDDEN,
        )

    cache_key = _social_share_state_cache_key(request.user.id, job.id)
    state = {
        "created_at_ts": int(timezone.now().timestamp()),
        "redirected_at_ts": None,
    }
    cache.set(cache_key, state, timeout=SOCIAL_SHARE_STATE_TTL_SECONDS)

    token = _make_social_share_token(request.user.id, job.id)
    redirect_urls = _build_share_redirect_urls(request, job.id, token)

    payload = _build_share_payload(request.user.id)
    payload.update(redirect_urls)
    return Response(payload)


@api_view(["GET"])
@permission_classes([AllowAny])
def share_redirect(request, job_id: int, platform: str):
    """
    Server-tracked social share redirect.

    We cannot reliably verify a share happened on social networks, but we can at least
    avoid trusting a client-side "confirm" flag by tracking that the user opened a
    server-generated share URL.
    """
    token = request.query_params.get("s", "")
    if not token:
        return Response(
            format_error(code="missing_share_token", message="Missing share token"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token_payload = _read_social_share_token(token)
    except Exception as exc:
        return Response(
            format_error(code="invalid_share_token", message=str(exc)),
            status=status.HTTP_400_BAD_REQUEST,
        )

    user_id = token_payload.get("u")
    token_job_id = token_payload.get("j")
    if not user_id or not token_job_id:
        return Response(
            format_error(code="invalid_share_token", message="Invalid token payload"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if int(token_job_id) != int(job_id):
        return Response(
            format_error(code="invalid_share_token", message="Token/job mismatch"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        RestorationJob.objects.get(id=job_id, user_id=user_id)
    except RestorationJob.DoesNotExist:
        return Response(
            format_error(code="not_found", message="Job not found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    cache_key = _social_share_state_cache_key(int(user_id), int(job_id))
    state = cache.get(cache_key) or {}
    created_at_ts = state.get("created_at_ts")
    if not created_at_ts:
        return Response(
            format_error(code="share_flow_expired", message="Share flow expired"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    state["redirected_at_ts"] = int(timezone.now().timestamp())
    cache.set(cache_key, state, timeout=SOCIAL_SHARE_STATE_TTL_SECONDS)

    share_payload = _build_share_payload(int(user_id))
    target_url = share_payload.get(platform)
    if not isinstance(target_url, str):
        return Response(
            format_error(code="invalid_platform", message="Invalid share platform"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = HttpResponseRedirect(target_url)
    response["Referrer-Policy"] = "no-referrer"
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def confirm_share(request, job_id):
    """
    Confirm social share and unlock.
    """
    try:
        job = RestorationJob.objects.get(id=job_id, user=request.user)
    except RestorationJob.DoesNotExist:
        return Response(
            format_error(code="not_found", message="Job not found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if job.status != "completed":
        return Response(
            format_error(
                code="invalid_state",
                message="Restoration not completed",
                details={"status": job.status},
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if job.unlocked_at:
        return Response(
            format_error(code="already_unlocked", message="Already unlocked"),
            status=status.HTTP_409_CONFLICT,
        )

    if request.user.social_share_unlock_used:
        return Response(
            format_error(
                code="social_share_used",
                message="Social share unlock already used",
            ),
            status=status.HTTP_403_FORBIDDEN,
        )

    cache_key = _social_share_state_cache_key(request.user.id, job.id)
    state = cache.get(cache_key) or {}
    redirected_at_ts = state.get("redirected_at_ts")
    if not redirected_at_ts:
        return Response(
            format_error(
                code="share_not_initiated",
                message="Share was not initiated via server redirect",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if SOCIAL_SHARE_CONFIRM_MIN_DELAY_SECONDS:
        now_ts = int(timezone.now().timestamp())
        if now_ts - int(redirected_at_ts) < SOCIAL_SHARE_CONFIRM_MIN_DELAY_SECONDS:
            return Response(
                format_error(
                    code="share_confirm_too_soon",
                    message="Please wait a moment before confirming",
                    details={"min_delay_seconds": SOCIAL_SHARE_CONFIRM_MIN_DELAY_SECONDS},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

    with transaction.atomic():
        user = User.objects.select_for_update().get(id=request.user.id)
        if user.social_share_unlock_used:
            return Response(
                format_error(
                    code="social_share_used",
                    message="Social share unlock already used",
                ),
                status=status.HTTP_403_FORBIDDEN,
            )

        user.social_share_unlock_used = True
        user.save(update_fields=["social_share_unlock_used"])

        job.unlock_method = "social_share"
        job.unlocked_at = timezone.now()
        job.save(update_fields=["unlock_method", "unlocked_at"])

    cache.delete(cache_key)
    return Response({"full_image_url": job.restored_full_url})
