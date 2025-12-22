# reviv.pics - Photo Restoration Micro-SaaS

Django REST API backend for photo restoration using Google's Nano Banana Pro model via kie.ai.

## Features

- OAuth authentication (Google, Apple, Facebook, Microsoft)
- Passkey authentication (WebAuthn)
- Photo restoration pipeline with watermarked preview
- Unlock full-res images via credits or social share
- Credit packs via Stripe + webhook reconciliation
- Celery tasks for processing and cleanup
- Cloudinary storage and transformations

## Tech Stack

- Backend: Django 6.0 + Django REST Framework
- Auth: django-allauth + fido2
- Payments: Stripe
- Storage: Cloudinary
- Queue/Cache: Celery + Redis
- DB: PostgreSQL (prod) / SQLite (dev)

## Quick Start

### Prerequisites

- Python 3.12+
- Redis (Celery broker/result backend)
- Cloudinary account
- Stripe account
- kie.ai API key

### Install

```bash
cd server
uv venv
source .venv/bin/activate
uv sync
```

All backend commands below are meant to be run from the `server/` directory (where the backend `pyproject.toml` lives).

### Environment

Copy `.env.example` to `.env` and fill credentials:

```bash
cd server
cp .env.example .env
```

Required variables:
- `DJANGO_SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CLOUDINARY_URL`
- `KIE_API_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- OAuth provider IDs/secrets
- `FRONTEND_URL`
- `AUTH_COOKIE_DOMAIN` (optional, for refresh cookie on subdomains)

### Migrations

```bash
cd server
uv run manage.py migrate
```

### Create credit packs

```bash
cd server
uv run manage.py create_credit_packs
```

### Run server

```bash
cd server
uv run manage.py runserver
```

### Celery

```bash
cd server
uv run celery -A config worker -l info
uv run celery -A config beat -l info
```

## API Docs

- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI Schema: `http://localhost:8000/api/schema/`

## API Endpoints

### Auth

- `POST /api/auth/oauth/initiate/`
- `GET /api/auth/oauth/callback/{provider}/`
- `POST /api/auth/oauth/exchange/` (SPA: exchange one-time ticket for tokens + refresh cookie)
- `POST /api/auth/token/refresh/` (SPA: refresh access token from HttpOnly refresh cookie)
- `POST /api/auth/passkey/register/begin/`
- `POST /api/auth/passkey/register/complete/`
- `POST /api/auth/passkey/login/begin/`
- `POST /api/auth/passkey/login/complete/`
- `POST /api/auth/logout/`
- `GET /api/auth/me/`

## Secure Google OAuth (React SPA)

Recommended production flow when serving the app on `https://reviv.pics`:
- The OAuth callback does NOT return JWTs in the URL.
- The backend redirects to the frontend with a short-lived one-time `ticket`.
- The frontend exchanges the `ticket` and receives:
  - `access` token in JSON (store in memory, not localStorage)
  - `reviv_refresh` in an HttpOnly cookie (used for refresh)

High-level steps:
1) `POST /api/auth/oauth/initiate/` with:
   - `provider="google"`
   - `return_to="https://reviv.pics/auth/callback"`
2) Redirect the browser to the returned `auth_url`
3) Google redirects to `GET /api/auth/oauth/callback/google/`
4) Backend redirects to `https://reviv.pics/auth/callback?ticket=...`
5) Frontend calls `POST /api/auth/oauth/exchange/` with the `ticket`
6) Use `POST /api/auth/token/refresh/` to refresh access tokens via the HttpOnly cookie

### Restorations

- `POST /api/restorations/upload/`
- `GET /api/restorations/{job_id}/status/`
- `GET /api/restorations/history/`
- `POST /api/restorations/{job_id}/unlock/`
- `POST /api/restorations/{job_id}/share-unlock/`
- `POST /api/restorations/{job_id}/confirm-share/`
- `DELETE /api/restorations/{job_id}/`

### Payments & Credits

- `GET /api/credits/packs/`
- `POST /api/credits/purchase/`
- `POST /api/credits/webhook/`
- `GET /api/credits/transactions/`

### Utilities

- `GET /api/health/`

## Tests

```bash
cd server
uv run manage.py test
```
