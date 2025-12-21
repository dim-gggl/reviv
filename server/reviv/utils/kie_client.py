import requests
import time
from typing import Dict, Optional
from django.conf import settings


class KieAIClient:
    """Client for interacting with kie.ai API"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.KIE_API_KEY
        self.base_url = settings.KIE_API_URL
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

    def create_task(self, image_url: str, prompt: str) -> Dict:
        """
        Create a new restoration task

        Args:
            image_url: URL of the image to restore
            prompt: Restoration prompt instructions

        Returns:
            dict with taskId
        """
        url = f"{self.base_url}/jobs/createTask"
        payload = {
            'model': 'nano-banana-pro',
            'input': {
                'prompt': prompt,
                'aspect_ratio': 'auto',
                'resolution': '2K',
                'output_format': 'png',
                'image_input': [image_url]
            }
        }

        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()

        result = response.json()
        if result['code'] != 200:
            raise Exception(f"kie.ai API error: {result}")

        return result['data']

    def check_status(self, task_id: str) -> Dict:
        """
        Check the status of a restoration task

        Args:
            task_id: The task ID to check

        Returns:
            dict with state and output_url (if completed)
        """
        url = f"{self.base_url}/jobs/recordInfo"
        params = {'taskId': task_id}

        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()

        result = response.json()
        if result['code'] != 200:
            raise Exception(f"kie.ai API error: {result}")

        return result['data']

    def wait_for_completion(self, task_id: str, max_wait_seconds: int = 600) -> Dict:
        """
        Poll task status until completion or timeout

        Args:
            task_id: The task ID to wait for
            max_wait_seconds: Maximum time to wait (default 10 minutes)

        Returns:
            Final task status data

        Raises:
            TimeoutError: If task doesn't complete in time
        """
        start_time = time.time()
        poll_interval = 5  # seconds

        while time.time() - start_time < max_wait_seconds:
            status = self.check_status(task_id)

            if status['state'] in ['success', 'failed']:
                return status

            time.sleep(poll_interval)

        raise TimeoutError(f"Task {task_id} did not complete within {max_wait_seconds} seconds")


# Singleton instance
kie_client = KieAIClient()