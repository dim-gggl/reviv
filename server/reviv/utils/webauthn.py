import base64
from typing import Any


def webauthn_bytes_to_json_bytes(value: bytes) -> list[int]:
    """
    Convert raw bytes to a JSON-safe byte array (list of ints 0-255).

    This format is easy to consume in the browser:
        new Uint8Array(challenge).buffer
    """
    return list(value)


def webauthn_json_bytes_to_bytes(value: Any) -> bytes:
    """
    Convert a JSON WebAuthn binary field into raw bytes.

    Supported inputs:
    - list[int]: JSON byte array
    - str: base64url (padding optional)
    """
    if isinstance(value, list):
        return bytes(value)

    if isinstance(value, str):
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    raise ValueError("Unsupported WebAuthn binary value type")


def webauthn_normalize_credential_id(value: Any) -> str:
    """
    Normalize a credential id coming from the frontend into a canonical base64url string.

    This helps DB lookups when the frontend sends a byte-array or a base64url string.
    """
    if isinstance(value, list):
        return base64.urlsafe_b64encode(bytes(value)).decode("utf-8")

    if isinstance(value, str):
        try:
            raw = webauthn_json_bytes_to_bytes(value)
        except Exception:
            return value
        return base64.urlsafe_b64encode(raw).decode("utf-8")

    raise ValueError("Unsupported credential id value type")


