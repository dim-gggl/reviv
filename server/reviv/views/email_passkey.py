import base64

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from fido2 import cbor
from fido2.server import Fido2Server
from fido2.webauthn import PublicKeyCredentialRpEntity, PublicKeyCredentialUserEntity
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from reviv.models import Passkey
from reviv.utils import format_error
from reviv.utils.webauthn import webauthn_bytes_to_json_bytes, webauthn_json_bytes_to_bytes

User = get_user_model()


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8")


rp_id = "localhost" if settings.DEBUG else "localhost"
if settings.ALLOWED_HOSTS:
    rp_id = settings.ALLOWED_HOSTS[0]

rp = PublicKeyCredentialRpEntity(id=rp_id, name="reviv.pics")
server = Fido2Server(rp)


@api_view(["POST"])
@permission_classes([AllowAny])
def email_passkey_register_begin(request):
    """
    Start passkey registration for email-only users (no OAuth)

    POST /api/auth/email-passkey/register/begin/
    {
        "email": "user@example.com"
    }

    Returns WebAuthn challenge for passkey registration
    """
    email = request.data.get("email", "").strip().lower()
    if not email:
        return Response(
            format_error(code="missing_email", message="Email is required"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        validate_email(email)
    except ValidationError:
        return Response(
            format_error(code="invalid_email", message="Invalid email format"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Only create users via email-passkey if they don't exist
    try:
        user = User.objects.get(email=email)
        # User exists - verify they're email-passkey compatible
        if user.oauth_provider:
            return Response(
                format_error(
                    code="oauth_user_exists",
                    message="This email is associated with an OAuth account. Please use OAuth login.",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        # User exists and is email-passkey based - proceed
    except User.DoesNotExist:
        # Create new email-passkey user
        user = User.objects.create(
            email=email,
            username=email,
            is_active=True,
        )
        # Password is already set to unusable by User.save()

    user_entity = PublicKeyCredentialUserEntity(
        id=str(user.id).encode("utf-8"),
        name=user.email,
        display_name=user.email,
    )

    existing_credentials = []
    for pk in Passkey.objects.filter(user=user):
        try:
            credential_id = webauthn_json_bytes_to_bytes(pk.credential_id)
        except Exception:
            continue
        existing_credentials.append({"type": "public-key", "id": credential_id})

    registration_data, state = server.register_begin(
        user=user_entity,
        credentials=existing_credentials,
        user_verification="preferred",
    )

    # Store state in session for completion step
    # SECURITY: The complete endpoint MUST verify webauthn_registration_user_id matches
    # the user entity encoded in the WebAuthn challenge to prevent session hijacking
    request.session["webauthn_registration_state"] = _urlsafe_b64encode(state)
    request.session["webauthn_registration_user_id"] = user.id

    options = cbor.decode(registration_data)
    challenge_b64 = _urlsafe_b64encode(options["challenge"])
    user_id_b64 = _urlsafe_b64encode(options["user"]["id"])
    return Response(
        {
            "challenge": webauthn_bytes_to_json_bytes(options["challenge"]),
            "challenge_b64": challenge_b64,
            "rp": options["rp"],
            "user": {
                "id": webauthn_bytes_to_json_bytes(options["user"]["id"]),
                "id_b64": user_id_b64,
                "name": options["user"]["name"],
                "displayName": options["user"]["displayName"],
            },
            "pubKeyCredParams": options["pubKeyCredParams"],
            "timeout": options.get("timeout", 60000),
            "attestation": options.get("attestation", "none"),
            "authenticatorSelection": options.get("authenticatorSelection", {}),
        }
    )
