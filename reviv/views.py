import json, logging, os

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from botocore.exceptions import ClientError

from .const import PROMPT as DEFAULT_PROMPT
from .models import PhotoRestoration
from .services import ImageEnhancementService

logger = logging.getLogger(__name__)


def home(request):
    if not request.user.is_authenticated:
        return render(request, "reviv/preview.html")

    recent_restorations = PhotoRestoration.objects.filter(
        user=request.user,
        status="completed",
    )[:6]
    return render(
        request,
        "reviv/home.html",
        {
            "recent_restorations": recent_restorations,
            "default_prompt": DEFAULT_PROMPT,
        },
    )


@login_required
def upload(request):
    if request.method == "POST":
        print(f"DEBUG: request.FILES == {request.FILES}")
        image = request.FILES.get("image")
        if not image:
            return JsonResponse({"error": "No image provided"}, status=400)
        try:
            restoration = PhotoRestoration.objects.create(
                user=request.user,
                original_image=image,
                prompt=DEFAULT_PROMPT,
                status="pending",
            )
        except ClientError as exc:
            # Keep this non-fatal and actionable: do not dump a full traceback 
            # for expected misconfiguration.
            response = getattr(exc, "response", {}) or {}
            err = response.get("Error", {}) or {}
            code = err.get("Code") or "Unknown"
            message = err.get("Message") or str(exc) or "Unknown error"
            request_id = (
                response.get("ResponseMetadata", {}) or {}
            ).get("RequestId")

            logger.warning(
                "S3 upload failed (code=%s request_id=%s): %s",
                code,
                request_id,
                message,
            )
            return JsonResponse(
                {
                    "error": (
                        "Failed to store uploaded image. Check S3 configuration "
                        f"(credentials/region/endpoint/signature): {exc}"
                    ),
                    "s3_error_code": code,
                    "s3_request_id": request_id,
                },
                status=502,
            )
        except Exception as e:
            raise e
        return JsonResponse({"success": True, "restoration_id": str(restoration.id)})

    return redirect("reviv:home")


@login_required
def process(request, restoration_id):
    restoration = get_object_or_404(
        PhotoRestoration, id=restoration_id, user=request.user
    )

    if restoration.status == "completed" and restoration.enhanced_image:
        return JsonResponse(
            {
                "status": "completed",
                "enhanced_image_url": restoration.enhanced_image.url,
            }
        )

    if restoration.status == "failed":
        return JsonResponse(
            {"status": "failed", "error": restoration.error_message or "Unknown error"}
        )

    if restoration.status == "processing":
        return JsonResponse({"status": "processing"})

    # pending: start the task
    try:
        task_id = ImageEnhancementService.start(
            restoration, restoration.prompt or DEFAULT_PROMPT
        )

        if not os.getenv("KIE_CALLBACK_URL", "").strip():
            ImageEnhancementService.finalize_by_polling(restoration)

        return JsonResponse({"status": "processing", "task_id": task_id})

    except Exception as exc:
        raise exc



@csrf_exempt
def kie_callback(request):
    """
    Public callback endpoint for Kie.ai callBackUrl.
    Keep it fast: validate + enqueue async finalize + return 200.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        payload = json.load(request.body)
    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=400)

    try:
        ImageEnhancementService.finalize_from_callback(payload)
    except Exception as e:
        raise e

    return JsonResponse({"status": "success"}, status=200)


@login_required
def result(request, restoration_id):
    restoration = get_object_or_404(
        PhotoRestoration, id=restoration_id, user=request.user
    )
    return render(request, "reviv/result.html", {"restoration": restoration})


@login_required
def gallery(request):
    restorations = PhotoRestoration.objects.filter(
        user=request.user, status="completed"
    )
    return render(request, "reviv/gallery.html", {"restorations": restorations})
