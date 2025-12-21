from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework import status


def exception_handler(exc, context):
    """
    Custom exception handler for DRF that returns consistent error format.
    """
    response = drf_exception_handler(exc, context)

    if response:
        response.data = format_error(
            code=getattr(exc, "default_code", "error"),
            message=str(exc),
            details=(
                response.data
                if isinstance(response.data, dict)
                else {"detail": response.data}
            ),
        )

    return response


def format_error(code: str, message: str, details=None):
    return {
        "error": {
            "code": str(code).upper(),
            "message": message,
            "details": details if details is not None else {},
        }
    }


class InsufficientCreditsError(Exception):
    """Raised when user doesn't have enough credits"""
    def __init__(self, credits_available, credits_needed):
        self.credits_available = credits_available
        self.credits_needed = credits_needed
        super().__init__(f"Insufficient credits. Have {credits_available}, need {credits_needed}")


class HistoryLimitExceeded(Exception):
    """Raised when user has too many active restoration jobs"""
    def __init__(self, max_jobs=6):
        self.max_jobs = max_jobs
        super().__init__(f"Maximum {max_jobs} images in history. Delete or unlock one to continue")


class AlreadyUnlockedError(Exception):
    """Raised when trying to unlock an already unlocked image"""
    def __init__(self):
        super().__init__("This image has already been unlocked")


class SocialShareAlreadyUsedError(Exception):
    """Raised when user tries to use social share unlock more than once"""
    def __init__(self):
        super().__init__("You have already used your one-time social share unlock")
