# reviv.pics API (Frontend Developer Guide)

This document explains **how to call every API endpoint** exposed by this repository.

## Base URLs

- **API base**: `/api/`
- **Health**: `/api/health/`
- **OpenAPI schema**: `/api/schema/`
- **Swagger UI**: `/api/docs/`
- **ReDoc**: `/api/redoc/`

In local development, the Django server is typically served on `http://localhost:8000`, so the full API base becomes:
- `http://localhost:8000/api/`

## Common conventions

### Authentication

Most endpoints require an **access JWT**:

- Send: `Authorization: Bearer <access_token>`
- Access token lifetime is **15 minutes** (see `SIMPLE_JWT`).

Some auth flows also use:

- **Refresh token**: returned as JSON in some endpoints, or stored as an **HttpOnly cookie** named `reviv_refresh` (recommended for browsers).
- **WebAuthn state nonce**: returned by `begin` endpoints (`registration_id` or `authentication_id`) and required by the matching `complete` endpoint.

#### When you must send cookies

For the following endpoints, your frontend must send cookies (credentials) so the backend can read/write the refresh cookie:

- `POST /api/auth/oauth/exchange/` (sets `reviv_refresh`)
- `POST /api/auth/token/refresh/` (reads `reviv_refresh` if present)
None of the WebAuthn/passkey endpoints require cookies; they rely on the `registration_id` / `authentication_id` returned by the `begin` step.

**Fetch example (browser):**

```ts
await fetch("/api/auth/token/refresh/", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  credentials: "include", // IMPORTANT
  body: JSON.stringify({}),
});
```

**CORS note (cross-origin SPA):**
If your frontend is hosted on a different origin, you must ensure CORS is configured to allow credentials (`CORS_ALLOW_CREDENTIALS=True`) and allow your origin (`CORS_ALLOWED_ORIGINS`).

### Content types

- **JSON endpoints**: send `Content-Type: application/json`
- **Upload endpoint**: send `multipart/form-data` with a file field named `image`

### Error format

Most errors follow the structure:

```json
{
  "error": {
    "code": "SOME_CODE",
    "message": "Human readable message",
    "details": {}
  }
}
```

Notes:
- `code` is usually **uppercased** by `format_error`.
- A few endpoints may return simpler error payloads in edge cases, but you should handle both.

### HTTP status codes (common)

- `200 OK`: success
- `201 Created`: created (upload)
- `400 Bad Request`: missing/invalid input
- `401 Unauthorized`: missing/invalid access token (or not authenticated)
- `403 Forbidden`: authenticated but not allowed (e.g., insufficient credits)
- `404 Not Found`: resource not found
- `409 Conflict`: resource already unlocked / conflict
- `500 Internal Server Error`: unexpected server error

## Quickstart: recommended browser auth strategy

Recommended for SPAs:

1. Use OAuth redirect flow with `return_to`, then redeem the `ticket` with `oauth_exchange`.
2. Store the **access token** in memory (not localStorage).
3. Store the **refresh token** as HttpOnly cookie (`reviv_refresh`) set by `oauth_exchange`.
4. When an API call returns `401`, call `POST /api/auth/token/refresh/` (with credentials) to get a new access token.

## Endpoints

### API Root

#### `GET /api/`

Returns a map of useful endpoints for browsing/debugging.

Response: `200 OK`

### Health

#### `GET /api/health/`

Returns health information for database/cache/celery.

Response: `200 OK` (healthy) or `503` (degraded)

```json
{
  "status": "healthy",
  "checks": { "database": "ok", "cache": "ok", "celery": "ok" }
}
```

---

## Auth (OAuth + JWT + Cookies)

#### `POST /api/auth/oauth/initiate/`

Initiate OAuth and get an authorization URL to redirect the user to.

Body (JSON):

```json
{
  "provider": "google",
  "return_to": "/auth/callback"
}
```

Notes:
- Only `"google"` is supported in this codebase.
- `return_to` is optional. If provided, it must be:
  - a relative path starting with `/`, or
  - an absolute URL with the same origin as `FRONTEND_URL`.

Response: `200 OK`

```json
{ "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..." }
```

Frontend action:
- redirect browser to `auth_url`

#### `GET|POST /api/auth/oauth/callback/<provider>/`

OAuth provider callback endpoint (normally visited by the browser).

Inputs:
- query params (typical): `?code=...&state=...`
- OR provider error params: `?error=...&error_description=...`

Success behavior depends on whether `return_to` was provided during initiate:

- **If `return_to` was provided**: returns `302 Redirect` to `return_to?ticket=...`
- **If `return_to` was not provided**: returns JSON with tokens

Success response (JSON mode): `200 OK`

```json
{
  "access": "<jwt_access>",
  "refresh": "<jwt_refresh>",
  "user": { "...": "..." }
}
```

#### `POST /api/auth/oauth/exchange/`

Redeem the short-lived OAuth ticket (received on frontend after redirect).

Body (JSON):

```json
{ "ticket": "<ticket_from_callback_query_param>" }
```

Response: `200 OK`
- Sets cookie: `reviv_refresh=<refresh_token>` (HttpOnly)
- Returns JSON:

```json
{
  "access": "<jwt_access>",
  "user": { "...": "..." }
}
```

Frontend notes:
- call with `credentials: "include"` so cookies are stored

#### `POST /api/auth/token/refresh/`

Get a new access token using:
- refresh cookie (`reviv_refresh`) **preferred**
- or refresh token in request body

Body (JSON, optional):

```json
{ "refresh": "<jwt_refresh>" }
```

Response: `200 OK`

```json
{ "access": "<new_jwt_access>" }
```

#### `GET /api/auth/me/`

Get current authenticated user.

Auth:
- `Authorization: Bearer <access>`

Response: `200 OK`

User shape comes from `UserSerializer`:
- `id`, `email`, `first_name`, `last_name`
- `credit_balance` (usually a stringified decimal)
- `free_preview_used`, `social_share_unlock_used`
- `created_at`

#### `POST /api/auth/logout/`

Logs out by removing the refresh cookie.

Auth:
- `Authorization: Bearer <access>`

Response: `200 OK`

```json
{ "message": "Successfully logged out" }
```

---

## Passkeys (WebAuthn)

These endpoints are a minimal WebAuthn API:
- `begin` returns options (challenge, rpId, allowCredentials...)
- `complete` consumes the browser credential response

Important:
- The backend stores WebAuthn state in cache and returns a short-lived nonce.
- Your frontend must send `registration_id` / `authentication_id` back to the matching `complete` endpoint.

### Register passkey (for already authenticated users)

#### `POST /api/auth/passkey/register/begin/`

Auth:
- `Authorization: Bearer <access>`

Response: `200 OK`

```json
{
  "registration_id": "<nonce>",
  "challenge": [0, 1, 2],
  "challenge_b64": "<base64url>",
  "rp": { "id": "localhost", "name": "reviv.pics" },
  "user": {
    "id": [0, 1, 2],
    "id_b64": "<base64url>",
    "name": "user@example.com",
    "displayName": "..."
  },
  "pubKeyCredParams": [...],
  "timeout": 60000,
  "attestation": "none",
  "authenticatorSelection": {}
}
```

Frontend:
- Build a `PublicKeyCredentialCreationOptions` and call `navigator.credentials.create(...)`.

#### `POST /api/auth/passkey/register/complete/`

Auth:
- `Authorization: Bearer <access>`
- Cookies required (session)

Body (JSON):

```json
{
  "name": "My MacBook",
  "registration_id": "<nonce>",
  "credential": {
    "clientDataJSON": "<base64url>",
    "attestationObject": "<base64url>"
  }
}
```

Response: `200 OK`

```json
{ "message": "Passkey registered successfully", "device_name": "My MacBook" }
```

### Login with passkey

#### `POST /api/auth/passkey/login/begin/`

Auth: none

Response: `200 OK`

```json
{
  "authentication_id": "<nonce>",
  "challenge": [0, 1, 2],
  "challenge_b64": "<base64url>",
  "timeout": 60000,
  "rpId": "localhost",
  "allowCredentials": [{ "type": "public-key", "id": [0, 1, 2], "id_b64": "<base64url>" }],
  "userVerification": "preferred"
}
```

Frontend:
- Build a `PublicKeyCredentialRequestOptions` and call `navigator.credentials.get(...)`.

#### `POST /api/auth/passkey/login/complete/`

Auth: none

Cookies required (session)

Body (JSON):

```json
{
  "authentication_id": "<nonce>",
  "credential": {
    "id": "<base64url_credential_id>",
    "clientDataJSON": "<base64url>",
    "authenticatorData": "<base64url>",
    "signature": "<base64url>"
  }
}
```

Response: `200 OK`

```json
{
  "access": "<jwt_access>",
  "refresh": "<jwt_refresh>",
  "user": { "...": "..." }
}
```

---

## Email-passkey (registration)

#### `POST /api/auth/email-passkey/register/begin/`

Starts passkey registration for an email-only user (no OAuth).

Auth: none

Body (JSON):

```json
{ "email": "newuser@example.com" }
```

Response: `200 OK`
- Same shape as `passkey/register/begin` (includes `registration_id`)

Notes:
- If the user already exists and has `oauth_provider`, the endpoint returns `400` (`OAUTH_USER_EXISTS`).

#### `POST /api/auth/email-passkey/register/complete/`

Finalize email-only passkey registration.

Auth: none

Body (JSON):

```json
{
  "registration_id": "<nonce>",
  "credential": {
    "clientDataJSON": "<base64url>",
    "attestationObject": "<base64url>"
  }
}
```

Response: `200 OK`

```json
{ "message": "Passkey registered successfully", "device_name": "Unnamed Device" }
```

---

## Restorations

All restoration endpoints require:
- `Authorization: Bearer <access>`

### Upload

#### `POST /api/restorations/upload/`

Content-Type: `multipart/form-data`

Form fields:
- `image`: file (JPG/PNG/WEBP)

Validation rules:
- max size: **10MB**
- formats: **JPG, PNG, WEBP**
- minimum dimension: **500px** on shortest side
- server uploads to Cloudinary and schedules a background job

Response: `201 Created`

```json
{ "job_id": 123, "status": "pending" }
```

Errors:
- `403 history_limit`: user already has 6 active jobs
- `400 validation_error`: file invalid
- `500 upload_failed`: Cloudinary upload failed

### Status (polling)

#### `GET /api/restorations/<job_id>/status/`

Response: `200 OK`

```json
{
  "job_id": 123,
  "status": "processing",
  "preview_url": null,
  "error": null
}
```

When completed:
- `status = "completed"`
- `preview_url` is set to `restored_preview_url`

When failed:
- `status = "failed"`
- `error = "Restoration failed"`

### History

#### `GET /api/restorations/history/`

Returns up to **6** non-expired jobs.

Response: `200 OK`

Shape comes from `RestorationJobSerializer`:
- `id`, `original_image_url`, `restored_preview_url`, `restored_full_url`
- `status`, `unlock_method`, `unlocked_at`, `is_unlocked`
- `created_at`, `expires_at`

### Delete

#### `DELETE /api/restorations/<job_id>/`

Deletes the job and attempts to delete Cloudinary assets.

Response: `200 OK`

```json
{ "message": "Job deleted successfully", "status": "ok" }
```

### Unlock with credits

#### `POST /api/restorations/<job_id>/unlock/`

Consumes **1 credit** and returns the full image URL.

Response: `200 OK`

```json
{
  "full_image_url": "https://...",
  "credits_remaining": "4.00"
}
```

Errors:
- `400 invalid_state`: job not completed
- `403 insufficient_credits`: not enough credits
- `409 already_unlocked`: job already unlocked

### Social share unlock (one-time per user)

#### `POST /api/restorations/<job_id>/share-unlock/`

Returns share URLs/payload needed to share the product.

Response: `200 OK`

```json
{
  "facebook": "https://<api-host>/api/restorations/<job_id>/share-redirect/facebook/?s=<token>",
  "twitter": "https://<api-host>/api/restorations/<job_id>/share-redirect/twitter/?s=<token>",
  "linkedin": "https://<api-host>/api/restorations/<job_id>/share-redirect/linkedin/?s=<token>",
  "pinterest": "https://<api-host>/api/restorations/<job_id>/share-redirect/pinterest/?s=<token>",
  "instagram": {
    "type": "manual",
    "caption": "I just restored...",
    "deep_link": "instagram://app"
  }
}
```

Notes:
- Social networks do not provide a reliable API to verify a "real" share.
- To avoid trusting a client-side "I shared" flag, the backend tracks a **server redirect**
  that must be opened before confirming.

Errors:
- `400 invalid_state`: job not completed
- `404 not_found`: job not found
- `403 social_share_used`: user already used the one-time share unlock
- `409 already_unlocked`: job already unlocked

#### `GET /api/restorations/<job_id>/share-redirect/<platform>/?s=<token>`

Opens a server-tracked redirect URL and then redirects to the actual social platform share URL.
Supported platforms: `facebook`, `twitter`, `linkedin`, `pinterest`.

This endpoint:
- Validates a short-lived signed token
- Records that the share URL was opened (server-side)
- Responds with `302` redirect to the platform URL

#### `POST /api/restorations/<job_id>/confirm-share/`

Marks `social_share_unlock_used=true` and unlocks the job.

Response: `200 OK`

```json
{ "full_image_url": "https://..." }
```

Errors:
- `400 invalid_state`: job not completed
- `404 not_found`: job not found
- `403 social_share_used`: user already used the one-time share unlock
- `409 already_unlocked`: job already unlocked
- `400 share_not_initiated`: share redirect was not opened (or expired)

---

## Credits / Payments (Stripe)

All user-facing credit endpoints require:
- `Authorization: Bearer <access>`

#### `GET /api/credits/packs/`

List purchasable credit packs.

Response: `200 OK`

```json
[
  {
    "id": 1,
    "sku": "PACK_5",
    "credits": 5,
    "price_cents": 499,
    "price_dollars": "$4.99",
    "active": true
  }
]
```

#### `GET /api/credits/transactions/`

List last 50 credit transactions.

Response: `200 OK`

```json
[
  { "id": 10, "amount": 5, "transaction_type": "purchase", "created_at": "..." },
  { "id": 11, "amount": -1, "transaction_type": "unlock", "created_at": "..." }
]
```

#### `POST /api/credits/purchase/`

Create a Stripe Checkout session and return a checkout URL.

Body (JSON):

```json
{ "sku": "PACK_5" }
```

Response: `200 OK`

```json
{ "checkout_url": "https://checkout.stripe.com/..." }
```

Frontend:
- Redirect the user to `checkout_url`.
- After payment, Stripe will redirect to:
  - `FRONTEND_URL/payment/success?session_id=...` or
  - `FRONTEND_URL/payment/cancelled`

#### `POST /api/credits/webhook/` (SERVER-TO-SERVER ONLY)

Stripe webhook endpoint (do not call from frontend).

Auth: none (signature verified via `STRIPE_WEBHOOK_SECRET`)

Response: `200 OK` or `400` for invalid signature/payload.

---

## Appendix: minimal request helper

```ts
type ApiError = {
  error: { code: string; message: string; details?: unknown };
};

export async function api<T>(
  path: string,
  accessToken?: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    throw data as ApiError;
  }
  return data as T;
}
```
