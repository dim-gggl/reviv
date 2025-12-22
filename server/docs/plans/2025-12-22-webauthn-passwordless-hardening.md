# WebAuthn Hardening + Email/Passkey Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Secure WebAuthn authentication with cache-backed state, cryptographic verification, replay protection, and complete the email/passkey registration flow.

**Architecture:** Replace session-based WebAuthn state with cache entries keyed by nonce and TTL, enforce verification via `Fido2Server.register_complete`/`authenticate_complete`, validate sign counters, and add rate limiting to passkey endpoints. Add an unauthenticated email-passkey registration completion endpoint that uses the cached state to create passkeys for email-only users.

**Tech Stack:** Django 6.0, Django REST Framework, fido2, django-ratelimit, Django cache

---

### Task 1: Add cache-backed WebAuthn state helpers

**Files:**
- Modify: `reviv/utils/webauthn.py`
- Test: `reviv/tests/unit_tests/test_unit_utils.py`

**Step 1: Write the failing test**

Add to `reviv/tests/unit_tests/test_unit_utils.py`:

```python
from django.core.cache import cache
from reviv.utils.webauthn import webauthn_store_state, webauthn_pop_state


def test_webauthn_state_roundtrip():
    cache.clear()
    state = b"state-bytes"
    payload = {"user_id": 123, "state": state}

    key = webauthn_store_state("register", payload, ttl_seconds=60)
    loaded = webauthn_pop_state("register", key)

    assert loaded["user_id"] == 123
    assert loaded["state"] == state
    assert webauthn_pop_state("register", key) is None
```

**Step 2: Run test to verify it fails**

Run: `uv run manage.py test reviv.tests.unit_tests.test_unit_utils -v 2`
Expected: FAIL with `ImportError` or missing functions

**Step 3: Write minimal implementation**

Update `reviv/utils/webauthn.py`:

```python
import secrets
from django.core.cache import cache

WEBAUTHN_STATE_TTL_SECONDS = 300
WEBAUTHN_STATE_PREFIX = "reviv:webauthn"


def _webauthn_state_key(flow: str, nonce: str) -> str:
    return f"{WEBAUTHN_STATE_PREFIX}:{flow}:{nonce}"


def webauthn_store_state(flow: str, payload: dict, ttl_seconds: int = WEBAUTHN_STATE_TTL_SECONDS) -> str:
    nonce = secrets.token_urlsafe(32)
    cache.set(_webauthn_state_key(flow, nonce), payload, timeout=ttl_seconds)
    return nonce


def webauthn_pop_state(flow: str, nonce: str) -> dict | None:
    key = _webauthn_state_key(flow, nonce)
    payload = cache.get(key)
    if payload:
        cache.delete(key)
    return payload
```

**Step 4: Run test to verify it passes**

Run: `uv run manage.py test reviv.tests.unit_tests.test_unit_utils -v 2`
Expected: PASS

**Step 5: Commit**

Suggest: commit the changes.

---

### Task 2: Harden passkey register begin (cache state + registration_id)

**Files:**
- Modify: `reviv/views/passkey.py`
- Test: `reviv/tests/unit_tests/test_passkey_views.py`

**Step 1: Write the failing test**

Add to `reviv/tests/unit_tests/test_passkey_views.py`:

```python
from unittest.mock import patch
from reviv.utils.webauthn import webauthn_pop_state

@patch("reviv.views.passkey.webauthn_store_state")
def test_begin_passkey_registration_returns_registration_id(mock_store_state, self):
    mock_store_state.return_value = "reg_nonce"
    response = self.client.post("/api/auth/passkey/register/begin/")
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.data["registration_id"], "reg_nonce")
```

**Step 2: Run test to verify it fails**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: FAIL (missing registration_id / state storage)

**Step 3: Implement minimal changes**

Update `reviv/views/passkey.py` to:
- store `state` in cache via `webauthn_store_state("register", {"user_id": user.id, "state": state})`
- return `registration_id` in response
- remove session writes for `webauthn_registration_state`

**Step 4: Run test to verify it passes**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: PASS

**Step 5: Commit**

Suggest: commit the changes.

---

### Task 3: Harden passkey register complete (verify + cache state)

**Files:**
- Modify: `reviv/views/passkey.py`
- Test: `reviv/tests/unit_tests/test_passkey_views.py`

**Step 1: Write the failing test**

Add to `reviv/tests/unit_tests/test_passkey_views.py`:

```python
@patch("reviv.views.passkey.webauthn_pop_state")
@patch("reviv.views.passkey.server")
def test_register_complete_uses_cached_state(mock_server, mock_pop_state, self):
    mock_pop_state.return_value = {"user_id": self.user.id, "state": b"state"}
    mock_server.register_complete.return_value = Mock(
        credential_id=b"cred",
        public_key={"kty": "EC"},
        sign_count=1,
    )

    response = self.client.post(
        "/api/auth/passkey/register/complete/",
        {
            "registration_id": "reg_nonce",
            "credential": {
                "clientDataJSON": [1, 2, 3],
                "attestationObject": [4, 5, 6],
            },
        },
        format="json",
    )

    self.assertEqual(response.status_code, 200)
    self.assertTrue(Passkey.objects.filter(user=self.user).exists())
```

**Step 2: Run test to verify it fails**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: FAIL (registration_id not supported, session-based state)

**Step 3: Implement minimal changes**

Update `reviv/views/passkey.py` to:
- require `registration_id` in request body
- load state via `webauthn_pop_state("register", registration_id)`
- verify `user_id` matches authenticated user
- call `server.register_complete` with decoded data
- store credential id and public key (encode with base64/cbor)

**Step 4: Run test to verify it passes**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: PASS

**Step 5: Commit**

Suggest: commit the changes.

---

### Task 4: Harden passkey login begin (cache state + authentication_id)

**Files:**
- Modify: `reviv/views/passkey.py`
- Test: `reviv/tests/unit_tests/test_passkey_views.py`

**Step 1: Write the failing test**

Add to `reviv/tests/unit_tests/test_passkey_views.py`:

```python
@patch("reviv.views.passkey.webauthn_store_state")
def test_begin_passkey_login_returns_authentication_id(mock_store_state, self):
    mock_store_state.return_value = "auth_nonce"
    response = self.client.post("/api/auth/passkey/login/begin/")
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.data["authentication_id"], "auth_nonce")
```

**Step 2: Run test to verify it fails**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: FAIL

**Step 3: Implement minimal changes**

Update `reviv/views/passkey.py` to:
- store `state` via `webauthn_store_state("login", {"state": state})`
- return `authentication_id` in response
- remove session writes for `webauthn_auth_state`

**Step 4: Run test to verify it passes**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: PASS

**Step 5: Commit**

Suggest: commit the changes.

---

### Task 5: Harden passkey login complete (verify + sign_count replay)

**Files:**
- Modify: `reviv/views/passkey.py`
- Test: `reviv/tests/unit_tests/test_passkey_views.py`

**Step 1: Write the failing test**

Add to `reviv/tests/unit_tests/test_passkey_views.py`:

```python
@patch("reviv.views.passkey.webauthn_pop_state")
@patch("reviv.views.passkey.server")
def test_login_complete_rejects_replay(mock_server, mock_pop_state, self):
    mock_pop_state.return_value = {"state": b"state"}
    mock_server.authenticate_complete.return_value = Mock(new_sign_count=1)

    passkey = Passkey.objects.create(
        user=self.user,
        credential_id="cred",
        public_key="cGtleQ==",
        sign_count=2,
        name="Device",
    )

    response = self.client.post(
        "/api/auth/passkey/login/complete/",
        {
            "authentication_id": "auth_nonce",
            "credential": {
                "id": "cred",
                "clientDataJSON": [1],
                "authenticatorData": [2],
                "signature": [3],
            },
        },
        format="json",
    )

    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.data["error"]["code"], "REPLAY_DETECTED")
```

**Step 2: Run test to verify it fails**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: FAIL

**Step 3: Implement minimal changes**

Update `reviv/views/passkey.py` to:
- require `authentication_id` and load state via `webauthn_pop_state("login", authentication_id)`
- decode credential fields and call `server.authenticate_complete`
- compare new sign count with stored `passkey.sign_count`
- reject if `new_sign_count <= passkey.sign_count` with `REPLAY_DETECTED`
- update `sign_count` and `last_used_at` on success

**Step 4: Run test to verify it passes**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: PASS

**Step 5: Commit**

Suggest: commit the changes.

---

### Task 6: Add email-passkey register complete (AllowAny)

**Files:**
- Create: `reviv/views/email_passkey_complete.py` or modify `reviv/views/email_passkey.py`
- Modify: `reviv/urls.py`
- Test: `reviv/tests/unit_tests/test_email_passkey_views.py`

**Step 1: Write the failing test**

Add to `reviv/tests/unit_tests/test_email_passkey_views.py`:

```python
@patch("reviv.views.email_passkey.webauthn_pop_state")
@patch("reviv.views.email_passkey.server")
def test_email_passkey_register_complete_creates_passkey(mock_server, mock_pop_state, self):
    user = User.objects.create(email="new@example.com", username="new@example.com")
    mock_pop_state.return_value = {"user_id": user.id, "state": b"state"}
    mock_server.register_complete.return_value = Mock(
        credential_id=b"cred",
        public_key={"kty": "EC"},
        sign_count=1,
    )

    response = self.client.post(
        "/api/auth/email-passkey/register/complete/",
        {
            "registration_id": "reg_nonce",
            "credential": {
                "clientDataJSON": [1],
                "attestationObject": [2],
            },
        },
        format="json",
    )

    self.assertEqual(response.status_code, 200)
    self.assertTrue(Passkey.objects.filter(user=user).exists())
```

**Step 2: Run test to verify it fails**

Run: `uv run manage.py test reviv.tests.unit_tests.test_email_passkey_views -v 2`
Expected: FAIL (404)

**Step 3: Implement minimal changes**

Update `reviv/views/email_passkey.py` to:
- add `email_passkey_register_complete` (AllowAny)
- load state via `webauthn_pop_state("register", registration_id)`
- fetch user by `user_id` in state
- call `server.register_complete` and create Passkey

Update `reviv/urls.py` to add:
- `path("auth/email-passkey/register/complete/", email_passkey.email_passkey_register_complete, name="email_passkey_register_complete")`

**Step 4: Run test to verify it passes**

Run: `uv run manage.py test reviv.tests.unit_tests.test_email_passkey_views -v 2`
Expected: PASS

**Step 5: Commit**

Suggest: commit the changes.

---

### Task 7: Add rate limiting to passkey endpoints

**Files:**
- Modify: `reviv/views/passkey.py`
- Modify: `reviv/views/email_passkey.py`
- Test: `reviv/tests/unit_tests/test_passkey_views.py`

**Step 1: Write the failing test**

Add to `reviv/tests/unit_tests/test_passkey_views.py`:

```python
from django.test.utils import override_settings

@override_settings(RATELIMIT_ENABLE=True)
def test_passkey_login_begin_rate_limited(self):
    for _ in range(6):
        response = self.client.post("/api/auth/passkey/login/begin/")
    self.assertIn(response.status_code, [429, 403])
```

**Step 2: Run test to verify it fails**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: FAIL (no rate limiting applied)

**Step 3: Implement minimal changes**

Apply `@ratelimit` decorators (from `django_ratelimit.decorators`) to:
- `passkey_register_begin`, `passkey_register_complete` (5/min IP + 5/min user)
- `passkey_login_begin`, `passkey_login_complete` (10/min IP)
- `email_passkey_register_begin`, `email_passkey_register_complete` (5/min IP)

**Step 4: Run test to verify it passes**

Run: `uv run manage.py test reviv.tests.unit_tests.test_passkey_views -v 2`
Expected: PASS

**Step 5: Commit**

Suggest: commit the changes.

---

### Task 8: Update frontend API docs for new WebAuthn parameters

**Files:**
- Modify: `READMYAPI.md`

**Step 1: Update documentation**

Document:
- `registration_id` returned by `register/begin` and required by `register/complete`
- `authentication_id` returned by `login/begin` and required by `login/complete`
- new endpoint `POST /api/auth/email-passkey/register/complete/`

**Step 2: Commit**

Suggest: commit the changes.

---

## Plan complete

Plan saved to `docs/plans/2025-12-22-webauthn-passwordless-hardening.md`.

Two execution options:
1) Subagent-Driven (this session) - I dispatch a fresh subagent per task, review between tasks.
2) Parallel Session (separate) - open a new session with executing-plans and run task-by-task.

Which approach do you want?
