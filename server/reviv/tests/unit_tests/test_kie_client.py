from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from reviv.utils.kie_client import KieAIClient


class KieAIClientTest(SimpleTestCase):
    @patch("reviv.utils.kie_client.requests.post")
    def test_create_task_success(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 200, "data": {"taskId": "task_123"}}
        mock_post.return_value = response

        client = KieAIClient(api_key="test-key")
        result = client.create_task(image_url="https://example.com/img.jpg", prompt="test")

        self.assertEqual(result["taskId"], "task_123")
        called_url = mock_post.call_args[0][0]
        self.assertEqual(called_url, f"{client.base_url}/jobs/createTask")
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["input"]["image_input"], ["https://example.com/img.jpg"])
        self.assertEqual(payload["input"]["prompt"], "test")

    @patch("reviv.utils.kie_client.requests.post")
    def test_create_task_raises_on_api_error(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 400, "message": "bad request"}
        mock_post.return_value = response

        client = KieAIClient(api_key="test-key")
        with self.assertRaises(Exception):
            client.create_task(image_url="https://example.com/img.jpg", prompt="test")

    @patch("reviv.utils.kie_client.requests.get")
    def test_check_status_success(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 200, "data": {"state": "success", "output": ["url"]}}
        mock_get.return_value = response

        client = KieAIClient(api_key="test-key")
        result = client.check_status("task_123")

        self.assertEqual(result["state"], "success")
        called_url = mock_get.call_args[0][0]
        self.assertEqual(called_url, f"{client.base_url}/jobs/recordInfo")
        params = mock_get.call_args[1]["params"]
        self.assertEqual(params["taskId"], "task_123")

    @patch("reviv.utils.kie_client.time.sleep")
    def test_wait_for_completion_returns_on_success(self, _mock_sleep):
        client = KieAIClient(api_key="test-key")
        with patch.object(
            client,
            "check_status",
            side_effect=[
                {"state": "processing"},
                {"state": "success", "output": ["url"]},
            ],
        ):
            result = client.wait_for_completion("task_123", max_wait_seconds=10)

        self.assertEqual(result["state"], "success")

    @patch("reviv.utils.kie_client.time.sleep")
    def test_wait_for_completion_times_out(self, _mock_sleep):
        client = KieAIClient(api_key="test-key")
        with patch.object(client, "check_status", return_value={"state": "processing"}):
            with self.assertRaises(TimeoutError):
                client.wait_for_completion("task_123", max_wait_seconds=0)
