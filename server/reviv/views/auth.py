from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.utils import timezone
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers import registry
from allauth.socialaccount.providers.base.constants import AuthProcess
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error
from allauth.socialaccount.internal.flows import login as social_login_flow
import secrets
import logging
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from reviv.serializers import UserSerializer
from reviv.utils import format_error

User = get_user_model()

logger = logging.getLogger(__name__)

OAUTH_STATE_TTL_SECONDS = 10 * 60
OAUTH_STATE_CACHE_PREFIX = "reviv:oauth_state:"
OAUTH_TICKET_TTL_SECONDS = 60
OAUTH_TICKET_CACHE_PREFIX = "reviv:oauth_ticket:"
ALLOWED_OAUTH_PROVIDERS = {"google"}


def _get_param_anywhere(request, name: str):
    """
    Retrieve a parameter value from multiple possible request locations.

    Why this helper exists:
    - OAuth providers can send callback data as query parameters (typical GET callback).
    - Some providers and flows can send data via POST (e.g., `form_post` response mode).
    - DRF wraps Django requests and exposes data differently depending on the content type.

    This helper tries, in order:
    - DRF query params (`request.query_params`)
    - DRF parsed body (`request.data`)
    - Raw Django POST (`request._request.POST`)

    It returns the first "truthy" value encountered, otherwise `None`.
    """
    # DRF query params (GET)
    # Most OAuth callbacks provide values here: /callback?code=...&state=...
    if hasattr(request, "query_params"):
        val = request.query_params.get(name)
        if val:
            return val

    # DRF parsed body (JSON/multipart)
    # Some providers can POST back using form_post, and DRF may parse it into `request.data`.
    try:
        val = request.data.get(name)  # type: ignore[attr-defined]
        if val:
            return val
    except Exception:
        # Never leak parsing internals; fall through to the next source.
        print(f"=" * 20)
        print("An error occurred while getting the parameter from the request data")
        print(f"=" * 20)


    # Raw Django form POST
    # Last-resort: access the underlying Django HttpRequest to read form fields directly.
    try:
        val = request._request.POST.get(name)  # type: ignore[attr-defined]
        if val:
            return val
    except Exception:
        # Never leak parsing internals; fall through to the next source.
        print(f"=" * 20)
        print("An error occurred while getting the parameter from the request data")
        print(f"=" * 20)

    # If the param is missing from all sources, we return None and the caller decides how to respond.
    return None


def _get_social_app_for_request(request, provider: str) -> SocialApp:
    """
    Retrieve an `allauth.socialaccount.models.SocialApp` for a provider.

    We prefer a SocialApp linked to the current Site (django.contrib.sites) because that
    is the recommended multi-site configuration.

    Fallback behavior:
    - Some environments may have SocialApp entries not linked to any Site yet.
      In that case we return the first configured app for the provider.

    Raises:
    - `SocialApp.DoesNotExist` if no SocialApp is configured for the provider.
    """
    # Determine which "Site" this request is associated with (based on host/domain).
    site = get_current_site(request)
    # Look up SocialApp(s) for that provider (e.g., "google").
    qs = SocialApp.objects.filter(provider=provider)
    # Preferred: SocialApp explicitly attached to this Site.
    app = qs.filter(sites=site).first()
    if app:
        return app
    # Fallback: first app regardless of site association (useful in simple/dev setups).
    app = qs.first()
    if app:
        return app
    # Nothing configured: propagate a specific exception so callers can return a clean 400.
    raise SocialApp.DoesNotExist()


def _build_callback_url(request, provider: str) -> str:
    """
    Build the OAuth callback URL (absolute) for a given provider.

    This URL is used for:
    - the OAuth authorization request (`redirect_uri`)
    - the OAuth token exchange (must match the `redirect_uri` used previously)

    Important:
    - This path must stay aligned with URLConf: `/api/auth/oauth/callback/<provider>/`.
    """
    return request.build_absolute_uri(f"/api/auth/oauth/callback/{provider}/")


def _cache_state_key(state: str) -> str:
    """
    Build a cache key for storing OAuth state payloads.

    We store the state server-side to avoid relying on cookies and to reduce replay risk.
    """
    return f"{OAUTH_STATE_CACHE_PREFIX}{state}"


def _cache_ticket_key(ticket: str) -> str:
    """
    Build a cache key for storing short-lived OAuth tickets.

    Tickets are used in SPA flows where the callback returns a redirect to the frontend.
    """
    return f"{OAUTH_TICKET_CACHE_PREFIX}{ticket}"


def _get_frontend_url() -> str:
    """
    Return the configured frontend base URL (without trailing slash).

    Used to validate/normalize `return_to` redirects in the OAuth flow.
    """
    return (getattr(settings, "FRONTEND_URL", "http://localhost:3000") or "").strip().rstrip("/")


def _normalize_return_to(frontend_url: str, return_to: str) -> str:
    """
    Restrict redirects to the configured frontend origin.
    Accepts absolute URLs on the same origin or a relative path (starting with /).

    Security rationale:
    - `return_to` comes from the client, so it must be validated to avoid open redirects.
    - We only allow:
      - relative paths (e.g., `/auth/callback`)
      - absolute URLs with the same scheme + host as `FRONTEND_URL`
    - Anything else falls back to a safe default (`{frontend_url}/auth/callback`).
    """
    if not return_to:
        # Safe default if caller did not specify a return_to target.
        return f"{frontend_url}/auth/callback"

    candidate = return_to.strip()
    if candidate.startswith("/"):
        # Relative paths are safe because they stay on the configured frontend origin.
        return f"{frontend_url}{candidate}"

    parsed_frontend = urlparse(frontend_url)
    parsed_candidate = urlparse(candidate)

    if (
        parsed_frontend.scheme == parsed_candidate.scheme
        and parsed_frontend.netloc == parsed_candidate.netloc
    ):
        # Absolute URL is allowed only if it matches frontend origin exactly.
        return candidate

    # Fallback to a safe page when the candidate is not allowed.
    return f"{frontend_url}/auth/callback"


def _stash_oauth_ticket(ticket: str, payload: dict, ttl_seconds: int = OAUTH_TICKET_TTL_SECONDS) -> None:
    """
    Store a short-lived OAuth ticket payload in cache.

    This enables an OAuth callback that *redirects* to the frontend:
    - backend callback stores tokens server-side behind a random ticket
    - frontend exchanges that ticket for tokens via `oauth_exchange`

    Payload typically includes:
    - user_id
    - access token
    - refresh token
    """
    cache.set(_cache_ticket_key(ticket), payload, timeout=ttl_seconds)


def _pop_oauth_ticket(ticket: str) -> dict | None:
    """
    Retrieve-and-delete (consume) a ticket payload from cache.

    Tickets are one-time use to reduce replay risk. If the ticket is missing/expired,
    `None` is returned.
    """
    key = _cache_ticket_key(ticket)
    payload = cache.get(key)
    if payload:
        cache.delete(key)
    return payload


def _add_query_param(url: str, key: str, value: str) -> str:
    """
    Return a new URL with a query parameter set (overwriting if it already exists).

    We parse and rebuild the URL to avoid manual string concatenation pitfalls and to
    preserve existing query params.
    """
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))


def _refresh_cookie_max_age_seconds() -> int:
    """
    Compute the refresh cookie max-age based on SIMPLE_JWT settings.

    We derive the cookie lifetime from `SIMPLE_JWT.REFRESH_TOKEN_LIFETIME` when available.
    Fallback to 7 days to match the typical refresh lifetime described in project docs.
    """
    simple_jwt = getattr(settings, "SIMPLE_JWT", {}) or {}
    refresh_lifetime = simple_jwt.get("REFRESH_TOKEN_LIFETIME")
    if refresh_lifetime:
        return int(refresh_lifetime.total_seconds())
    return 7 * 24 * 60 * 60


def _stash_oauth_state(state: str, payload: dict, ttl_seconds: int = OAUTH_STATE_TTL_SECONDS) -> None:
    """
    Store OAuth state payload in cache (server-side).

    `state` is a one-time token used to:
    - prevent CSRF (bind callback to an initiation request)
    - prevent replay (we consume it on first use)

    Payload typically includes:
    - provider
    - created_at
    - optional PKCE code_verifier
    - optional normalized return_to URL
    """
    cache.set(_cache_state_key(state), payload, timeout=ttl_seconds)


def _pop_oauth_state(state: str) -> dict | None:
    """
    Retrieve-and-delete (consume) an OAuth state payload from cache.

    Consuming state makes callback handling idempotent and reduces replay risk. If the
    state does not exist or has expired, `None` is returned.
    """
    key = _cache_state_key(state)
    payload = cache.get(key)
    if payload:
        cache.delete(key)
    return payload


@api_view(['POST'])
@permission_classes([AllowAny])
def oauth_initiate(request):
    """
    Initiate an OAuth flow for a given provider and return the authorization URL.

    POST /api/auth/oauth/initiate/
    {
        "provider": "google|apple|facebook|microsoft"
    }

    Returns:
    {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
    }

    Notes:
    - This endpoint only prepares the redirect URL; the actual login happens in `oauth_callback`.
    - We generate and store a one-time `state` server-side for CSRF/replay protection.
    - We support optional `return_to` for SPA flows (validated to avoid open redirects).
    """
    # DRF wraps the underlying Django HttpRequest; allauth expects the raw Django request.
    django_request = getattr(request, "_request", request)

    # Normalize and validate the requested provider.
    provider = request.data.get("provider", "").strip()
    if not provider:
        return Response(
            format_error(code="missing_provider", message="Missing provider"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Project constraint: only Google OAuth is currently allowed.
    if provider not in ALLOWED_OAUTH_PROVIDERS:
        return Response(
            format_error(
                code="invalid_provider",
                message=f"Provider '{provider}' is not supported. Only Google OAuth is allowed.",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Resolve the provider class from allauth's registry (e.g., GoogleProvider).
        provider_cls = registry.get_class(provider)
    except Exception as e:
        # We do not expose provider registry internals; return a stable, generic error.
        logger.info("Invalid OAuth provider during initiate: %s", provider, exc_info=e)
        return Response(
            format_error(code="invalid_provider", message="Invalid provider"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Ensure we have a configured SocialApp (client_id/secret) for this  
        # provider.This is required to build a valid OAuth authorization URL.
        social_app = _get_social_app_for_request(django_request, provider)

        # Generate a one-time state (anti-CSRF + replay protection).
        # We store it server-side (cache) rather than in cookies, which 
        # keeps the flow compatible with strict browser privacy settings 
        # and cross-origin SPAs.
        state = secrets.token_urlsafe(32)

        # The callback URL must match what the provider expects 
        # (and what we use later for exchange).
        callback_url = _build_callback_url(django_request, provider)

        # Optional SPA redirect target. We normalize it to the configured 
        # frontend origin.
        frontend_url = _get_frontend_url()
        return_to = request.data.get("return_to", "").strip()
        normalized_return_to = ""
        if return_to:
            # Only keep `return_to` if it's on the configured frontend origin.
            normalized_return_to = _normalize_return_to(frontend_url, return_to)

        # Provider-specific adapter exposes endpoints (authorize/token URLs), 
        # scope delimiter, and other OAuth2-specific behavior.
        provider_obj = provider_cls(django_request, app=social_app)
        oauth2_adapter = provider_obj.get_oauth2_adapter(django_request)

        # Build authorization request parameters.
        # allauth provider implementation can add provider-specific 
        # params (e.g., prompt, access_type).
        auth_params = provider_obj.get_auth_params()

        # PKCE (Proof Key for Code Exchange) support:
        # - `code_verifier` must be kept server-side until the 
        # callback to redeem the auth code.
        # - other PKCE params (e.g., code_challenge) are added 
        # to the authorization request.
        pkce_params = provider_obj.get_pkce_params()
        code_verifier = pkce_params.pop("code_verifier", None)
        auth_params.update(pkce_params)

        # Determine OAuth scopes to request from the provider.
        scope = provider_obj.get_scope()

        # Persist state payload for the callback:
        # - binds callback to initiation
        # - carries PKCE verifier and optional return_to info
        _stash_oauth_state(
            state,
            {
                "provider": provider,
                "created_at": timezone.now().isoformat(),
                "pkce_code_verifier": code_verifier,
                "return_to": normalized_return_to,
            },
        )

        # Create an OAuth2 client that can construct the 
        # authorization URL consistently and later exchange 
        # the authorization code for tokens.
        client = OAuth2Client(
            django_request,
            social_app.client_id,
            social_app.secret,
            oauth2_adapter.access_token_method,
            oauth2_adapter.access_token_url,
            callback_url,
            scope_delimiter=oauth2_adapter.scope_delimiter,
            headers=oauth2_adapter.headers,
            basic_auth=oauth2_adapter.basic_auth,
        )

        # The OAuth2Client uses `client.state` to add `state=` to the 
        # authorization URL.
        client.state = state

        # Final authorization URL the frontend will redirect the user to.
        auth_url = client.get_redirect_url(oauth2_adapter.authorize_url, scope, auth_params)

        # Return URL to the client; the client performs the redirect.
        return Response({"auth_url": auth_url})

    except SocialApp.DoesNotExist:
        # SocialApp missing means provider is not configured in admin.
        return Response(
            format_error(
                code="provider_not_configured",
                message=f"OAuth provider {provider} not configured",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        # Avoid leaking sensitive details (OAuth URLs, secrets, etc.).
        logger.exception("OAuth initiate failed for provider=%s", provider)
        return Response(
            format_error(code="oauth_initiate_failed", 
                         message="Failed to initiate OAuth flow"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def oauth_callback(request, provider):
    """
    Handle the OAuth callback for a provider and finalize the login.

    GET /api/auth/oauth/callback/{provider}/?code=xxx&state=xxx

    Returns:
    {
        "access": "jwt_access_token",
        "refresh": "jwt_refresh_token",
        "user": {...}
    }

    Flow overview:
    - Validate provider and retrieve cached state (anti-CSRF and replay 
    protection)
    - Exchange authorization code for access token (optionally with PKCE 
    verifier)
    - Let allauth complete the social login (create/link user + 
    SocialAccount)
    - Mint JWT tokens (SimpleJWT) for our API
    - Optionally redirect to the frontend with a short-lived ticket

    Security notes:
    - State is consumed (deleted) on first use to reduce replay.
    - We never return provider secrets or raw OAuth errors beyond sanitized 
    details.
    """
    try:
        # allauth expects Django HttpRequest; DRF's Request wraps it.
        django_request = getattr(request, "_request", request)
        provider = (provider or "").strip()

        # Enforce allowed providers at callback time as well (defense in depth).
        if provider not in ALLOWED_OAUTH_PROVIDERS:
            return Response(
                format_error(
                    code="invalid_provider",
                    message=f"Provider '{provider}' is not supported. Only Google OAuth is allowed.",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Resolve provider class from allauth registry.
            provider_cls = registry.get_class(provider)
        except Exception as e:
            # If registry lookup fails, do not leak exception details.
            logger.info("Invalid OAuth provider during callback: %s", provider, exc_info=e)
            return Response(
                {"error": "Invalid provider"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Provider might send errors/cancellation.
        # Examples: user denied consent, invalid_request, etc.
        err = _get_param_anywhere(request, "error")
        if err:
            desc = _get_param_anywhere(request, "error_description")
            return Response(
                format_error(
                    code="oauth_error",
                    message="OAuth error",
                    details={"provider_error": err, "description": desc},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        # `state` binds this callback to the corresponding initiation request 
        # and prevents CSRF.
        state = _get_param_anywhere(request, "state")
        if not state:
            return Response(
                format_error(code="missing_state", 
                             message="Missing state parameter"),
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Consume the state payload (one-time use).
        state_payload = _pop_oauth_state(state)
        if not state_payload:
            return Response(
                format_error(
                    code="invalid_state",
                    message="Invalid or expired state parameter",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Ensure the provider in the state matches the provider in the URL path.
        if state_payload.get("provider") != provider:
            return Response(
                format_error(code="state_mismatch", 
                             message="State/provider mismatch"),
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Authorization code is required to exchange for tokens.
        code = _get_param_anywhere(request, "code")
        if not code:
            return Response(
                format_error(code="missing_authorization_code",
                             message="No authorization code provided"),
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Retrieve SocialApp to know client_id/secret and ensure provider 
        # is configured.
        social_app = _get_social_app_for_request(django_request, provider)

        # Callback URL must match the one used during authorization 
        # (redirect_uri).
        callback_url = _build_callback_url(django_request, provider)

        # Build provider adapter (authorize/token URLs and token parsing 
        # logic).
        provider_obj = provider_cls(django_request, app=social_app)
        oauth2_adapter = provider_obj.get_oauth2_adapter(django_request)

        # Create OAuth2 client used to exchange the authorization code for 
        # tokens.
        client = OAuth2Client(
            django_request,
            social_app.client_id,
            social_app.secret,
            oauth2_adapter.access_token_method,
            oauth2_adapter.access_token_url,
            callback_url,
            scope_delimiter=oauth2_adapter.scope_delimiter,
            headers=oauth2_adapter.headers,
            basic_auth=oauth2_adapter.basic_auth,
        )

        # Exchange authorization code for token data.
        # PKCE: pass the verifier we stored during initiation (if the 
        # provider uses PKCE).
        access_token_data = client.get_access_token(
            code,
            pkce_code_verifier=state_payload.get("pkce_code_verifier"),
        )

        # Parse provider token response into allauth's token object.
        token = oauth2_adapter.parse_token(access_token_data)
        if social_app.pk:
            # Attach the SocialApp so allauth can persist the token with 
            # app relationship.
            token.app = social_app

        # Complete the login: fetch user profile from provider and build a 
        # SocialLogin instance.
        # `complete_login` typically calls the provider's profile endpoint 
        # (using access token).
        sociallogin = oauth2_adapter.complete_login(
            django_request,
            social_app,
            token,
            response=access_token_data,
        )
        sociallogin.token = token
        sociallogin.state = {
            "process": AuthProcess.LOGIN,
        }

        # Use allauth to lookup/create/link the user and SocialAccount 
        # robustly.
        # This handles:
        # - existing social account -> existing user
        # - new social account -> create user (subject to allauth settings)
        # - linking behavior and adapter hooks
        #
        # Note: allauth may internally create redirects/HTML responses in 
        # traditional flows.
        # We intentionally ignore that and return JSON (JWT) responses for 
        # our API.
        social_login_flow.complete_login(django_request, sociallogin, raises=True)

        # allauth should have produced a valid Django user at this point.
        user = sociallogin.user
        if not user or not getattr(user, "pk", None):
            return Response(
                format_error(
                    code="oauth_user_missing",
                    message="OAuth login did not produce a user",
                ),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Persist convenience fields on the local user model (optional).
        # These are not required by allauth but can be useful for analytics 
        # and debugging.
        try:
            user.oauth_provider = provider
            user.oauth_id = sociallogin.account.uid
            user.save(update_fields=["oauth_provider", "oauth_id"])
        except Exception:
            # Never fail authentication because of auxiliary field persistence issues.
            logger.exception(
                "Failed to persist OAuth convenience fields for user_id=%s provider=%s",
                getattr(user, "pk", None),
                provider,
            )

        # Mint JWT tokens for our API using SimpleJWT.
        refresh = RefreshToken.for_user(user)
        serializer = UserSerializer(user)

        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        # SPA redirect mode:
        # If the initiation call provided `return_to`, we redirect there with a short-lived
        # ticket instead of returning tokens directly. This avoids exposing 
        # tokens in URL fragments or query parameters.
        return_to = (state_payload.get("return_to") or "").strip()
        if return_to:
            # One-time ticket that maps to server-side stored tokens.
            ticket = secrets.token_urlsafe(32)
            _stash_oauth_ticket(
                ticket,
                {
                    "user_id": user.id,
                    "access": access_token,
                    "refresh": refresh_token,
                },
            )
            # Append ticket to return URL and redirect the browser to the frontend.
            redirect_url = _add_query_param(return_to, "ticket", ticket)
            return HttpResponseRedirect(redirect_url)

        # Non-redirect mode: return tokens directly to the caller (e.g., mobile client).
        return Response(
            {
                "access": access_token,
                "refresh": refresh_token,
                "user": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    except OAuth2Error:
        # Token exchange failed (invalid code, mismatched redirect_uri, etc.).
        return Response(
            format_error(
                code="oauth_exchange_failed",
                message="Failed to exchange authorization code for token",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    except SocialApp.DoesNotExist:
        # Provider not configured correctly in admin (missing SocialApp).
        return Response(
            format_error(
                code="provider_not_configured",
                message=f"OAuth provider {provider} not configured",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        # Defensive catch-all: log server-side and return a generic error.
        logger.exception(f"Unexpected OAuth callback error for provider={provider}")
        return Response(
            format_error(
                code="oauth_callback_error",
                message="Unexpected OAuth callback error",
            ),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_me(request):
    """
    Return the authenticated user's profile data.

    GET /api/auth/me/

    Returns:
    {
        "id": 1,
        "email": "user@example.com",
        "credit_balance": 5,
        ...
    }

    Notes:
    - Authentication is enforced via `IsAuthenticated`.
    - Serialization is handled by `UserSerializer`.
    """

    # Serialize the current authenticated user from the request context.
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def auth_logout(request):
    """
    Log out the current user (client-side token cleanup + refresh cookie deletion).

    POST /api/auth/logout/

    Returns:
    {
        "message": "Successfully logged out"
    }

    Notes:
    - This implementation removes the HttpOnly refresh cookie (`reviv_refresh`).
    - If token blacklisting is enabled, additional server-side invalidation 
    could be added.
    """
    # Delete refresh cookie so the browser cannot refresh sessions silently anymore.
    response = Response({"message": "Successfully logged out"})
    response.delete_cookie("reviv_refresh")
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def oauth_exchange(request):
    """
    Exchange a short-lived OAuth ticket for tokens and set the refresh cookie.

    Intended for SPA flows:
    - backend OAuth callback redirects to frontend with `ticket=...`
    - frontend calls this endpoint to redeem the ticket

    Response:
    - returns an access token and user payload in JSON
    - stores refresh token in an HttpOnly cookie (`reviv_refresh`)
    """
    # Ticket is passed by the frontend after it receives the redirect from 
    # `oauth_callback`.
    ticket = request.data.get("ticket", "").strip()
    if not ticket:
        return Response(
            format_error(code="missing_ticket", message="Missing ticket"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Consume ticket (one-time) and retrieve server-side payload.
    payload = _pop_oauth_ticket(ticket)
    if not payload:
        return Response(
            format_error(code="invalid_ticket", 
                         message="Invalid or expired ticket"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Payload should contain the user id that the ticket was created for.
    user_id = payload.get("user_id")
    if not user_id:
        return Response(
            format_error(code="invalid_ticket", 
                         message="Invalid ticket payload"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Load the user to return a full user profile payload.
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response(
            format_error(code="user_not_found", message="User not found"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Serialize user and extract tokens from payload.
    serializer = UserSerializer(user)
    access_token = payload.get("access", "")
    refresh_token = payload.get("refresh", "")

    # Return access token in the body; store refresh token in an HttpOnly 
    # cookie.
    response = Response(
        {
            "access": access_token,
            "user": serializer.data,
        },
        status=status.HTTP_200_OK,
    )

    # Cookie domain is configurable (useful for subdomain setups). 
    # Empty => default host-only cookie.
    cookie_domain = (getattr(settings, "AUTH_COOKIE_DOMAIN", "") or "").strip()
    response.set_cookie(
        "reviv_refresh",
        refresh_token,
        # HttpOnly prevents JS access; reduces XSS impact.
        httponly=True,
        # Secure cookies should be enabled outside DEBUG (HTTPS only).
        secure=not getattr(settings, "DEBUG", True),
        # Strict prevents most CSRF-like cross-site sending. Adjust if 
        # you need cross-site flows.
        samesite="Strict",
        max_age=_refresh_cookie_max_age_seconds(),
        domain=cookie_domain if cookie_domain else None,
        # Root path so API endpoints can read it regardless of route.
        path="/",
    )
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def token_refresh(request):
    """
    Refresh access token using the HttpOnly refresh cookie (preferred) or 
    a refresh token in body.

    This endpoint supports two client types:
    - Browser/SPA: sends refresh token as HttpOnly cookie (preferred).
    - Non-browser client: sends refresh token in request body.

    Response:
    - `{ "access": "<new_access_token>" }`
    """
    # Prefer cookie-based refresh for browsers (keeps refresh token out of 
    # JavaScript and storage).
    refresh_token = request.COOKIES.get("reviv_refresh", "").strip()
    if not refresh_token:
        # Fallback: allow explicit refresh token in body for non-browser clients.
        refresh_token = request.data.get("refresh", "").strip()
    if not refresh_token:
        return Response(
            format_error(code="missing_refresh", message="Missing refresh token"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Validate and parse refresh token, then mint a new access token.
        refresh = RefreshToken(refresh_token)
        return Response({"access": str(refresh.access_token)}, 
                        status=status.HTTP_200_OK)
    except Exception:
        # Any parsing/validation failure returns a stable, generic error.
        return Response(
            format_error(code="invalid_refresh", message="Invalid refresh token"),
            status=status.HTTP_400_BAD_REQUEST,
        )
