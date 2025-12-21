import base64

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from fido2 import cbor
from fido2.server import Fido2Server
from fido2.webauthn import PublicKeyCredentialRpEntity, PublicKeyCredentialUserEntity
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from reviv.models import Passkey
from reviv.serializers import UserSerializer
from reviv.utils import format_error
from reviv.utils.webauthn import (
    webauthn_bytes_to_json_bytes,
    webauthn_json_bytes_to_bytes,
    webauthn_normalize_credential_id,
)

User = get_user_model()


def _urlsafe_b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8")


rp_id = "localhost" if settings.DEBUG else "localhost"
if settings.ALLOWED_HOSTS:
    rp_id = settings.ALLOWED_HOSTS[0]

rp = PublicKeyCredentialRpEntity(id=rp_id, name="reviv.pics")
server = Fido2Server(rp)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def passkey_register_begin(request):
    user = request.user
    user_entity = PublicKeyCredentialUserEntity(
        id=str(user.id).encode("utf-8"),
        name=user.email or str(user.id),
        display_name=user.get_full_name() or user.email or str(user.id),
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

    request.session["webauthn_registration_state"] = _urlsafe_b64encode(state)

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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def passkey_register_complete(request):
    state_b64 = request.session.get("webauthn_registration_state")
    if not state_b64:
        return Response(
            format_error(
                code="registration_missing",
                message="No registration in progress",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    credential_data = request.data.get("credential") or {}
    if not credential_data:
        return Response(
            format_error(
                code="missing_credential",
                message="Missing credential data",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    client_data_b64 = credential_data.get("clientDataJSON")
    attestation_b64 = credential_data.get("attestationObject")
    if not client_data_b64 or not attestation_b64:
        return Response(
            format_error(
                code="missing_attestation",
                message="Missing attestation data",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        state = _urlsafe_b64decode(state_b64)
        client_data = webauthn_json_bytes_to_bytes(client_data_b64)
        attestation_object = webauthn_json_bytes_to_bytes(attestation_b64)
        auth_data = server.register_complete(
            state=state,
            client_data=client_data,
            attestation_object=attestation_object,
        )
    except Exception as exc:
        return Response(
            format_error(
                code="registration_failed",
                message=str(exc),
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    device_name = request.data.get("name") or "Unnamed Device"
    Passkey.objects.create(
        user=request.user,
        credential_id=_urlsafe_b64encode(auth_data.credential_id),
        public_key=_urlsafe_b64encode(cbor.encode(auth_data.public_key)),
        sign_count=auth_data.sign_count,
        name=device_name,
    )
    request.session.pop("webauthn_registration_state", None)

    return Response({"message": "Passkey registered successfully", "device_name": device_name})


@api_view(["POST"])
@permission_classes([AllowAny])
def passkey_login_begin(request):
    credentials = []
    for pk in Passkey.objects.all():
        try:
            credential_id = webauthn_json_bytes_to_bytes(pk.credential_id)
        except Exception:
            continue
        credentials.append({"type": "public-key", "id": credential_id})

    auth_data, state = server.authenticate_begin(
        credentials=credentials,
        user_verification="preferred",
    )

    request.session["webauthn_auth_state"] = _urlsafe_b64encode(state)

    options = cbor.decode(auth_data)
    challenge_b64 = _urlsafe_b64encode(options["challenge"])
    allow_credentials = [
        {
            "type": cred["type"],
            "id": webauthn_bytes_to_json_bytes(cred["id"]),
            "id_b64": _urlsafe_b64encode(cred["id"]),
        }
        for cred in options.get("allowCredentials", [])
    ]

    return Response(
        {
            "challenge": webauthn_bytes_to_json_bytes(options["challenge"]),
            "challenge_b64": challenge_b64,
            "timeout": options.get("timeout", 60000),
            "rpId": options.get("rpId"),
            "allowCredentials": allow_credentials,
            "userVerification": options.get("userVerification", "preferred"),
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def passkey_login_complete(request):
    state_b64 = request.session.get("webauthn_auth_state")
    if not state_b64:
        return Response(
            format_error(
                code="auth_missing",
                message="No authentication in progress",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    credential_data = request.data.get("credential") or {}
    if not credential_data:
        return Response(
            format_error(
                code="missing_credential",
                message="Missing credential data",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    credential_id_b64 = credential_data.get("id")
    if not credential_id_b64:
        return Response(
            format_error(
                code="missing_credential_id",
                message="Missing credential ID",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        credential_id_normalized = webauthn_normalize_credential_id(credential_id_b64)
    except Exception as exc:
        return Response(
            format_error(code="invalid_credential_id", message=str(exc)),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        passkey = Passkey.objects.get(credential_id=credential_id_normalized)
    except Passkey.DoesNotExist:
        return Response(
            format_error(code="unknown_credential", message="Unknown credential"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    passkey.last_used_at = timezone.now()
    passkey.sign_count += 1
    passkey.save(update_fields=["last_used_at", "sign_count"])

    refresh = RefreshToken.for_user(passkey.user)
    request.session.pop("webauthn_auth_state", None)

    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(passkey.user).data,
        }
    )
