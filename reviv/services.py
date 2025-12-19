import io
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from django.core.files.base import ContentFile
from django.db import transaction
from dotenv import load_dotenv
from PIL import Image

from .models import PhotoRestoration

load_dotenv()


@dataclass(frozen=True)
class KieTaskDetail:
    task_id: str
    state: str | None
    result_urls: list[str]
    fail_msg: str | None


class ImageEnhancementService:
    """
    Robust Kie.ai integration:
    - createTask once (stores taskId in DB)
    - finalize via callback when available (recommended)
    - fallback polling via recordInfo (dev/local or missing callback)
    - idempotent finalize (safe with duplicate callbacks)
    """

    CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
    RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

    # --- Public entrypoints -------------------------------------------------

    @staticmethod
    def start(restoration: PhotoRestoration, prompt: str) -> str:
        """
        Starts a Kie.ai enhancement task and stores taskId in DB.
        Returns taskId.
        """
        api_key = ImageEnhancementService._get_kie_api_key()
        headers = ImageEnhancementService._headers(api_key)

        model = os.getenv("KIE_MODEL", "nano-banana-pro")
        aspect_ratio = os.getenv("KIE_ASPECT_RATIO", "auto")
        resolution = os.getenv("KIE_RESOLUTION", "2K")
        output_format = os.getenv("KIE_OUTPUT_FORMAT", "png")

        image_url = ImageEnhancementService._get_public_source_url(restoration)

        callback_url = os.getenv("KIE_CALLBACK_URL", "").strip()
        payload: dict[str, Any] = {
            "model": model,
            "input": {
                "prompt": prompt,
                "image_input": [image_url],
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_format": output_format,
            },
        }
        if callback_url:
            payload["callBackUrl"] = callback_url

        data = ImageEnhancementService._post_json(
            ImageEnhancementService.CREATE_URL, headers, payload
        )
        ImageEnhancementService._raise_if_kie_error(data, context="createTask")

        task_id = ImageEnhancementService._extract_task_id(data)

        # Persist task id + status atomically.
        restoration.status = "processing"
        restoration.error_message = ""
        restoration.kie_task_id = task_id
        restoration.save(update_fields=["status", "error_message", "kie_task_id", "updated_at"])


        return task_id

    @staticmethod
    def finalize_from_callback(payload: dict[str, Any]) -> None:
        """
        Called by the callback view.
        Must return quickly in the view: we spawn a thread for heavy work.
        """
        task_id = ImageEnhancementService._extract_task_id(payload)
        if not task_id:
            raise ValueError("Callback payload missing taskId")

        # Run heavy work async to keep callback response fast (15s timeout).
        thread = threading.Thread(
            target=ImageEnhancementService._finalize_by_task_id,
            args=(task_id, payload),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def finalize_by_polling(restoration: PhotoRestoration) -> None:
        """
        Fallback path when callback is not available.
        Polls recordInfo until success/fail, then finalizes.
        """
        if not restoration.kie_task_id:
            raise RuntimeError("Missing kie_task_id; did you call start()?")

        task_id = restoration.kie_task_id
        thread = threading.Thread(
            target=ImageEnhancementService._finalize_by_task_id,
            args=(task_id, None),
            daemon=True,
        )
        thread.start()

    # --- Core finalize logic ------------------------------------------------

    @staticmethod
    def _finalize_by_task_id(
        task_id: str, callback_payload: dict[str, Any] | None
    ) -> None:
        """
        Idempotent finalization:
        - resolve restoration by task_id
        - if already completed, do nothing
        - otherwise fetch detail (prefer callback payload if it contains result)
        - download result, validate, store, mark completed
        """
        restoration = PhotoRestoration.objects.filter(kie_task_id=task_id).first()
        if not restoration:
            # Unknown taskId: ignore. You can log this if you want.
            return

        # Idempotence: if already completed, exit.
        restoration.refresh_from_db()
        if restoration.status == "completed" and restoration.enhanced_image:
            return

        try:
            detail = ImageEnhancementService._detail_from_callback_or_api(
                task_id, callback_payload
            )

            if detail.state == "fail":
                raise RuntimeError(detail.fail_msg or "Kie.ai job failed")

            if detail.state != "success":
                # Callback might be an intermediate "accepted" payload for some APIs.
                # In that case, do a short bounded poll.
                detail = ImageEnhancementService._poll_record_info(task_id)

            if not detail.result_urls:
                raise RuntimeError("Kie.ai success but no result URLs found")

            output_url = detail.result_urls[0]
            image_content = ImageEnhancementService._download_image(output_url)
            png_content = ImageEnhancementService._validate_and_reencode_png(
                image_content
            )

            # Store atomically to avoid partial writes.
            with transaction.atomic():
                locked = PhotoRestoration.objects.select_for_update().get(
                    id=restoration.id
                )
                if locked.status == "completed" and locked.enhanced_image:
                    return

                locked.enhanced_image.save(
                    f"enhanced_{locked.id}.png",
                    ContentFile(png_content),
                    save=False,
                )
                locked.status = "completed"
                locked.error_message = ""
                locked.save(
                    update_fields=[
                        "enhanced_image",
                        "status",
                        "error_message",
                        "updated_at",
                    ]
                )

        except Exception as exc:
            PhotoRestoration.objects.filter(id=restoration.id).update(
                status="failed",
                error_message=str(exc),
            )

    # --- Getting task detail ------------------------------------------------

    @staticmethod
    def _detail_from_callback_or_api(
        task_id: str, callback_payload: dict[str, Any] | None
    ) -> KieTaskDetail:
        """
        Supports:
        - Common API: data.state + data.resultJson (resultUrls)
        - Some callback formats: data.info.resultImageUrl
        Falls back to recordInfo.
        """
        if callback_payload:
            detail = ImageEnhancementService._parse_detail_like_record_info(
                task_id, callback_payload
            )
            if detail.state in ("success", "fail") or detail.result_urls:
                return detail

        # Fall back to API.
        return ImageEnhancementService._get_record_info(task_id)

    @staticmethod
    def _get_record_info(task_id: str) -> KieTaskDetail:
        api_key = ImageEnhancementService._get_kie_api_key()
        headers = ImageEnhancementService._headers(api_key)

        res = requests.get(
            ImageEnhancementService.RECORD_INFO_URL,
            params={"taskId": task_id},
            headers=headers,
            timeout=60,
        )
        if res.status_code != 200:
            raise RuntimeError(
                f"Kie.ai recordInfo failed ({res.status_code}): {res.text}"
            )

        data = res.json()
        ImageEnhancementService._raise_if_kie_error(data, context="recordInfo")
        return ImageEnhancementService._parse_detail_like_record_info(task_id, data)

    @staticmethod
    def _poll_record_info(task_id: str) -> KieTaskDetail:
        """
        Backoff strategy aligned with Kie docs:
        - start 2-3s
        - then 5-10s
        - then 15-30s
        Stop after ~10 minutes by default.
        """
        max_seconds = int(os.getenv("KIE_MAX_POLL_SECONDS", "600"))
        start = time.time()

        delays = [2, 2, 3, 5, 5, 10, 15, 20, 30]
        i = 0

        last = KieTaskDetail(task_id=task_id, state=None, result_urls=[], fail_msg=None)
        while True:
            if time.time() - start > max_seconds:
                raise TimeoutError(
                    f"Kie.ai timeout waiting for result (last_state={last.state})"
                )

            last = ImageEnhancementService._get_record_info(task_id)
            if last.state == "success":
                return last
            if last.state == "fail":
                raise RuntimeError(last.fail_msg or "Kie.ai job failed")

            delay = delays[min(i, len(delays) - 1)]
            i += 1
            time.sleep(delay)

    @staticmethod
    def _parse_detail_like_record_info(
        task_id: str, payload: dict[str, Any]
    ) -> KieTaskDetail:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = {}

        # Common API format
        state = data.get("state") if isinstance(data.get("state"), str) else None
        fail_msg = data.get("failMsg") if isinstance(data.get("failMsg"), str) else None

        result_urls: list[str] = []

        result_json = data.get("resultJson")
        if isinstance(result_json, str) and result_json.strip():
            try:
                parsed = json.loads(result_json)
                urls = parsed.get("resultUrls")
                if isinstance(urls, list):
                    result_urls = [u for u in urls if isinstance(u, str) and u]
            except json.JSONDecodeError:
                # Keep going; we may still have other formats.
                pass

        # Some callback formats (e.g. image callbacks) include data.info.resultImageUrl
        info = data.get("info")
        if isinstance(info, dict):
            url = (
                info.get("resultImageUrl") or info.get("result_url") or info.get("url")
            )
            if isinstance(url, str) and url:
                result_urls = result_urls or [url]

        return KieTaskDetail(
            task_id=task_id, state=state, result_urls=result_urls, fail_msg=fail_msg
        )

    # --- HTTP helpers -------------------------------------------------------

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _post_json(
        url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        res = requests.post(url, json=payload, headers=headers, timeout=60)
        if res.status_code != 200:
            raise RuntimeError(f"Kie.ai request failed ({res.status_code}): {res.text}")
        return res.json()

    # --- Existing utilities (kept & tightened) ------------------------------

    @staticmethod
    def _get_kie_api_key() -> str:
        api_key = os.getenv("KIE_API_KEY")
        if not api_key:
            raise RuntimeError("Missing KIE_API_KEY environment variable")
        return api_key

    @staticmethod
    def _download_image(url: str) -> bytes:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content

    @staticmethod
    def _validate_and_reencode_png(image_content: bytes) -> bytes:
        image = Image.open(io.BytesIO(image_content))
        image.load()

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")

        png_buffer = io.BytesIO()
        image.save(png_buffer, format="PNG", optimize=True)
        return png_buffer.getvalue()

    @staticmethod
    def _extract_task_id(response_data: dict[str, Any]) -> str:
        """
        Accepts both createTask and callback payloads.
        """
        if not isinstance(response_data, dict):
            return ""

        # Direct keys
        for k in ("taskId", "task_id", "id", "job_id", "recordId", "record_id"):
            v = response_data.get(k)
            if v:
                return str(v)

        data = response_data.get("data")
        if isinstance(data, dict):
            for k in ("taskId", "task_id", "id", "job_id", "recordId", "record_id"):
                v = data.get(k)
                if v:
                    return str(v)

        return ""

    @staticmethod
    def _raise_if_kie_error(response_data: dict[str, Any], *, context: str) -> None:
        """
        Many Kie endpoints return code=200 for success. Non-200 indicates error.
        """
        if not isinstance(response_data, dict):
            return

        code = response_data.get("code")
        if code is None:
            return

        try:
            numeric_code = int(code)
        except (TypeError, ValueError):
            return

        if numeric_code == 200:
            return

        message = (
            response_data.get("msg") or response_data.get("message") or "Unknown error"
        )
        raise RuntimeError(f"Kie.ai {context} error (code={numeric_code}): {message}")

    @staticmethod
    def _get_public_source_url(restoration: PhotoRestoration) -> str:
        """
        Kie.ai needs a publicly reachable http(s) URL for image_input.
        """
        try:
            image_url = restoration.original_image.url
        except Exception as exc:
            raise RuntimeError("Unable to resolve source image URL") from exc

        if not isinstance(image_url, str) or not image_url:
            raise RuntimeError("Source image URL is empty")

        if image_url.startswith("/"):
            public_media_base_url = os.environ.get("PUBLIC_MEDIA_BASE_URL").strip()

            if public_media_base_url:
                image_url = urljoin(public_media_base_url.rstrip("/") + "/", image_url.lstrip("/"))
            else:
                raise RuntimeError(
                    "Source image URL is relative. Configure public storage (e.g. S3) or set "
                    "PUBLIC_MEDIA_BASE_URL to a publicly reachable origin so the URL is accessible by Kie.ai."
                )

        if not (image_url.startswith("http://") or image_url.startswith("https://")):
            raise RuntimeError("Source image URL must be an http(s) URL")

        if any(host in image_url for host in ("localhost", "127.0.0.1", "0.0.0.0")):
            raise RuntimeError("Source image URL must be publicly reachable by Kie.ai")

        return image_url
