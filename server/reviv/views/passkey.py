import base64

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from fido2 import cbor
from fido2.cose import CoseKey
from fido2.server import Fido2Server
from fido2.utils import websafe_encode
from fido2.webauthn import (
    Aaguid,
    AttestedCredentialData,
    AuthenticatorData,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
)
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django_ratelimit.decorators import ratelimit

from reviv.models import Passkey
from reviv.serializers import UserSerializer
from reviv.utils import format_error
from reviv.utils.webauthn import (
    webauthn_bytes_to_json_bytes,
    webauthn_json_bytes_to_bytes,
    webauthn_normalize_credential_id,
    webauthn_pop_state,
    webauthn_store_state,
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


def _build_attested_credential(passkey: Passkey) -> AttestedCredentialData:
    credential_id = webauthn_json_bytes_to_bytes(passkey.credential_id)
    public_key_raw = webauthn_json_bytes_to_bytes(passkey.public_key)
    public_key = CoseKey.parse(cbor.decode(public_key_raw))
    return AttestedCredentialData.create(Aaguid.NONE, credential_id, public_key)


@ratelimit(group="passkey_register_begin", key="ip", rate="5/m", block=True)
@ratelimit(group="passkey_register_begin", key="user", rate="5/m", block=True)
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

    registration_id = webauthn_store_state(
        "register",
        {"user_id": user.id, "state": state},
    )

    options = cbor.decode(registration_data)
    challenge_b64 = _urlsafe_b64encode(options["challenge"])
    user_id_b64 = _urlsafe_b64encode(options["user"]["id"])
    return Response(
        {
            "registration_id": registration_id,
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


@ratelimit(group="passkey_register_complete", key="ip", rate="5/m", block=True)
@ratelimit(group="passkey_register_complete", key="user", rate="5/m", block=True)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def passkey_register_complete(request):
    registration_id = request.data.get("registration_id", "").strip()
    if not registration_id:
        return Response(
            format_error(
                code="registration_missing",
                message="No registration in progress",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    state_payload = webauthn_pop_state("register", registration_id)
    if not state_payload:
        return Response(
            format_error(
                code="registration_missing",
                message="No registration in progress",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    state = state_payload.get("state")
    user_id = state_payload.get("user_id")
    if not state or not user_id:
        return Response(
            format_error(
                code="registration_missing",
                message="No registration in progress",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if int(user_id) != int(request.user.id):
        return Response(
            format_error(
                code="registration_mismatch",
                message="Registration does not match authenticated user",
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

    return Response({"message": "Passkey registered successfully", "device_name": device_name})


@ratelimit(group="passkey_login_begin", key="ip", rate="10/m", block=True)
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

    authentication_id = webauthn_store_state(
        "login",
        {"state": state},
    )

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
            "authentication_id": authentication_id,
            "challenge": webauthn_bytes_to_json_bytes(options["challenge"]),
            "challenge_b64": challenge_b64,
            "timeout": options.get("timeout", 60000),
            "rpId": options.get("rpId"),
            "allowCredentials": allow_credentials,
            "userVerification": options.get("userVerification", "preferred"),
        }
    )


@ratelimit(group="passkey_login_complete", key="ip", rate="10/m", block=True)
@api_view(["POST"])
@permission_classes([AllowAny])
def passkey_login_complete(request):
    authentication_id = request.data.get("authentication_id", "").strip()
    if not authentication_id:
        return Response(
            format_error(
                code="auth_missing",
                message="No authentication in progress",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    state_payload = webauthn_pop_state("login", authentication_id)
    if not state_payload:
        return Response(
            format_error(
                code="auth_missing",
                message="No authentication in progress",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    state = state_payload.get("state")
    if not state:
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

    client_data_b64 = credential_data.get("clientDataJSON")
    auth_data_b64 = credential_data.get("authenticatorData")
    signature_b64 = credential_data.get("signature")
    if not client_data_b64 or not auth_data_b64 or not signature_b64:
        return Response(
            format_error(
                code="auth_failed",
                message="Missing assertion data",
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

    try:
        client_data = webauthn_json_bytes_to_bytes(client_data_b64)
        auth_data = webauthn_json_bytes_to_bytes(auth_data_b64)
        signature = webauthn_json_bytes_to_bytes(signature_b64)
        response_payload = {
            "id": credential_id_normalized,
            "rawId": credential_id_normalized,
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(client_data),
                "authenticatorData": websafe_encode(auth_data),
                "signature": websafe_encode(signature),
            },
        }
        credential = _build_attested_credential(passkey)
        server.authenticate_complete(state, [credential], response_payload)
        auth_data_obj = AuthenticatorData(auth_data)
    except Exception as exc:
        return Response(
            format_error(code="auth_failed", message=str(exc)),
            status=status.HTTP_400_BAD_REQUEST,
        )

    new_sign_count = auth_data_obj.counter
    if new_sign_count <= passkey.sign_count:
        return Response(
            format_error(code="replay_detected", message="Replay detected"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    passkey.last_used_at = timezone.now()
    passkey.sign_count = new_sign_count
    passkey.save(update_fields=["last_used_at", "sign_count"])

    refresh = RefreshToken.for_user(passkey.user)

    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(passkey.user).data,
        }
    )
