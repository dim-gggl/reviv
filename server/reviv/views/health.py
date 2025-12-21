from celery import current_app
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """
    Health check endpoint for monitoring.
    """
    checks = {}

    try:
        connection.ensure_connection()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    try:
        cache.set("health_check", "ok", 10)
        cached = cache.get("health_check")
        checks["cache"] = "ok" if cached == "ok" else "error"
    except Exception as exc:
        checks["cache"] = f"error: {exc}"

    try:
        broker_url = (getattr(settings, "CELERY_BROKER_URL", "") or "").strip()
        if not broker_url or broker_url.startswith("memory://"):
            checks["celery"] = "not configured"
        else:
            inspector = current_app.control.inspect()
            stats = inspector.stats() if inspector else None
            checks["celery"] = "ok" if stats else "no workers"
    except Exception as exc:
        checks["celery"] = f"error: {exc}"

    status_ok = all(value == "ok" for value in checks.values())

    return Response(
        {"status": "healthy" if status_ok else "degraded", "checks": checks},
        status=200 if status_ok else 503,
    )
