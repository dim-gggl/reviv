import json
from django.test import TestCase
from django.urls import reverse

from .services import ImageEnhancementService


class KieParsingTests(TestCase):
    def test_extract_task_id_from_data_task_id(self):
        payload = {"code": 200, "msg": "success", "data": {"taskId": "task_123"}}
        self.assertEqual(ImageEnhancementService._extract_task_id(payload), "task_123")

    def test_parse_record_info_success_extracts_result_urls(self):
        record_info = {
            "code": 200,
            "message": "success",
            "data": {
                "taskId": "task_123",
                "state": "success",
                "resultJson": json.dumps(
                    {"resultUrls": ["https://example.com/out.png"]}
                ),
            },
        }
        detail = ImageEnhancementService._parse_detail_like_record_info(
            "task_123", record_info
        )
        self.assertEqual(detail.state, "success")
        self.assertEqual(detail.result_urls, ["https://example.com/out.png"])

    def test_parse_record_info_fail_extracts_fail_msg(self):
        record_info = {
            "code": 200,
            "message": "success",
            "data": {
                "taskId": "task_123",
                "state": "fail",
                "failMsg": "Invalid prompt",
                "resultJson": "",
            },
        }
        detail = ImageEnhancementService._parse_detail_like_record_info(
            "task_123", record_info
        )
        self.assertEqual(detail.state, "fail")
        self.assertEqual(detail.fail_msg, "Invalid prompt")

    def test_raise_if_kie_error_ignores_success(self):
        ImageEnhancementService._raise_if_kie_error(
            {"code": 200, "msg": "success"}, context="any"
        )

    def test_raise_if_kie_error_raises_on_failure(self):
        with self.assertRaises(Exception):
            ImageEnhancementService._raise_if_kie_error(
                {"code": 500, "msg": "bad request"}, context="any"
            )


class AccessControlTests(TestCase):
    def test_home_anonymous_shows_demo_slider_only(self):
        response = self.client.get(reverse("reviv:home"))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'id="imageCompare"')
        self.assertContains(response, "reviv/demo/before.jpg")
        self.assertContains(response, "reviv/demo/after.png")

        self.assertNotContains(response, "Drop Image Here")
        self.assertNotContains(response, 'id="fileInput"')

    def test_gallery_requires_login(self):
        response = self.client.get(reverse("reviv:gallery"))
        self.assertIn(response.status_code, (302, 301))
