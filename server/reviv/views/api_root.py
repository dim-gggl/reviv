from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse


@api_view(["GET"])
@permission_classes([AllowAny])
def api_root(request, format=None):
    """
    API root endpoint to make the browsable API navigable.
    """
    return Response(
        {
            "health": reverse("health_check", request=request, format=format),
            "auth_me": reverse("auth_me", request=request, format=format),
            "auth_logout": reverse("auth_logout", request=request, format=format),
            "credits_packs": reverse("credit_packs", request=request, format=format),
            "credits_transactions": reverse(
                "credit_transactions", request=request, format=format
            ),
            "credits_purchase": reverse("credit_purchase", request=request, format=format),
            "restorations_upload": reverse("upload_image", request=request, format=format),
            "restorations_history": reverse(
                "restoration_history", request=request, format=format
            ),
            "restoration_status_template": "/api/restorations/{job_id}/status/",
            "restoration_unlock_template": "/api/restorations/{job_id}/unlock/",
            "restoration_share_unlock_template": "/api/restorations/{job_id}/share-unlock/",
            "restoration_confirm_share_template": "/api/restorations/{job_id}/confirm-share/",
            "restoration_delete_template": "/api/restorations/{job_id}/",
        }
    )


