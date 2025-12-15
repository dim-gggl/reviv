from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import close_old_connections
from .models import PhotoRestoration
from .services import ImageEnhancementService
from .const import PROMPT as DEFAULT_PROMPT
import json
import logging
import threading

logger = logging.getLogger(__name__)


def _json_login_required(view_func):
    """
    Return JSON 401 instead of redirecting to the login page.

    This avoids fetch() receiving HTML (login page) and failing to parse JSON.
    """
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        return view_func(request, *args, **kwargs)
    return _wrapped


def _run_enhancement_in_background(restoration_id):
    """
    Run the enhancement asynchronously to avoid blocking the HTTP request.

    The frontend expects /process/<id>/ to return quickly so it can poll for status.
    """
    try:
        close_old_connections()
        restoration = PhotoRestoration.objects.get(id=restoration_id)
    except PhotoRestoration.DoesNotExist:
        return

    try:
        ImageEnhancementService.enhance_image(restoration, restoration.prompt)
    except Exception:
        logger.exception("Enhancement failed for restoration_id=%s", restoration_id)
    finally:
        close_old_connections()


def home(request):
    """Display the main page.

    Unauthenticated users should only see the demo preview (no upload UI, no gallery content).
    """
    if not request.user.is_authenticated:
        return render(request, 'reviv/preview.html')

    recent_restorations = PhotoRestoration.objects.filter(
        user=request.user,
        status='completed',
    )[:6]
    return render(request, 'reviv/home.html', {
        'recent_restorations': recent_restorations,
        'default_prompt': DEFAULT_PROMPT
    })


@_json_login_required
def upload(request):
    """Handle image upload and create restoration job"""
    if request.method == 'POST':
        image = request.FILES.get('image')

        if not image:
            return JsonResponse({'error': 'No image provided'}, status=400)

        restoration = PhotoRestoration.objects.create(
            user=request.user,
            original_image=image,
            prompt=DEFAULT_PROMPT
        )

        return JsonResponse({
            'success': True,
            'restoration_id': str(restoration.id)
        })

    return redirect('home')


@_json_login_required
def process(request, restoration_id):
    """Process the image enhancement"""
    restoration = get_object_or_404(
        PhotoRestoration,
        id=restoration_id,
        user=request.user
    )

    if restoration.status == 'completed':
        return JsonResponse({
            'status': 'completed',
            'enhanced_image_url': restoration.enhanced_image.url
        })

    if restoration.status == 'failed':
        return JsonResponse({
            'status': 'failed',
            'error': restoration.error_message or 'Unknown error'
        })

    if restoration.status == 'processing':
        return JsonResponse({'status': 'processing'})

    # Start processing in the background and return immediately so the client can poll.
    updated = PhotoRestoration.objects.filter(
        id=restoration.id,
        user=request.user,
        status='pending'
    ).update(status='processing', error_message='')
    if updated == 0:
        # Another request already started/finished processing.
        restoration.refresh_from_db()
        return JsonResponse({'status': restoration.status})

    thread = threading.Thread(
        target=_run_enhancement_in_background,
        args=(restoration.id,),
        daemon=True
    )
    thread.start()

    return JsonResponse({'status': 'processing'})


@login_required
def result(request, restoration_id):
    """Display the restoration result"""
    restoration = get_object_or_404(
        PhotoRestoration,
        id=restoration_id,
        user=request.user
    )
    return render(request, 'reviv/result.html', {
        'restoration': restoration
    })


@login_required
def gallery(request):
    """Display gallery of completed restorations for the current user."""
    restorations = PhotoRestoration.objects.filter(
        user=request.user,
        status='completed',
    )
    return render(request, 'reviv/gallery.html', {
        'restorations': restorations
    })
