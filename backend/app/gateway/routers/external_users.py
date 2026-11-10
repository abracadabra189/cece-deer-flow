"""External user-system integration: phone-based provisioning and ticket login.

Two endpoints, one flow::

    operator's user system            browser
    ────────────────────────          ─────────────────────────────
    POST /api/v1/auth/external/provision
      { phone, username }  ──►  resolve-or-create the account
                            ◄──  { user_id, access_token, login_ticket, login_url }
    hand `login_url` to the user ──►  GET /api/v1/auth/external/login?ticket=…
                                      sets access_token + csrf_token cookies
                                      302 → /auth/callback?next=…  (already signed in)

``provision`` is server-to-server and authenticated **only** by the shared
``auth.external_user.api_key``; that key is worth an account for any phone
number, so it is an admin-grade secret (see
:class:`deerflow.config.auth_config.ExternalUserAuthConfig`). ``login`` is
public but consumes a short-lived, single-use signed ticket, so holding a ticket
is what authorizes it — the same shape as the OIDC callback.

The redirect reuses the existing frontend ``/auth/callback`` page, so no frontend
change is required and the token never lands in browser storage.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from starlette.responses import RedirectResponse

from app.gateway.auth.config import get_auth_config
from app.gateway.auth.external_provisioning import get_or_provision_external_user, normalize_phone, normalize_username
from app.gateway.auth.external_ticket import consume_external_login_ticket, create_external_login_ticket
from app.gateway.auth.jwt import create_access_token
from app.gateway.auth.session_cookie import set_session_cookie
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, _request_origin, auth_csrf_cookie_settings, generate_csrf_token
from app.gateway.deps import get_local_provider
from app.gateway.routers.auth import validate_next_param
from app.gateway.utils import constant_time_equals
from deerflow.config.auth_config import ExternalUserAuthConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/external", tags=["auth-external"])

#: Header carrying the shared provisioning key. ``Authorization: Bearer <key>``
#: is accepted as an alternative so callers with a generic HTTP client work too.
EXTERNAL_USER_KEY_HEADER = "X-External-User-Key"
#: Preference key holding the display name supplied by the external system.
EXTERNAL_USERNAME_PREFERENCE_KEY = "external_username"
#: Where a browser lands after a failed ticket redemption.
_LOGIN_ERROR_PATH = "/login?error=external_login_failed"


class ExternalProvisionRequest(BaseModel):
    """Provisioning call from the operator's user system."""

    phone: str = Field(description="The user's phone number; the identity key")
    username: str | None = Field(default=None, description="Display name to store alongside the account")
    next: str | None = Field(default=None, description="Optional relative path the browser lands on after login")


class ExternalProvisionResponse(BaseModel):
    """Credentials for one provisioned user."""

    user_id: str
    phone: str
    username: str | None = None
    email: str = Field(description="The reserved synthetic address derived from the phone; a storage key, not a mailbox")
    system_role: str
    created: bool = Field(description="True when this call registered the account")
    token_type: str = "Bearer"
    access_token: str = Field(description="Session JWT. Use it as the access_token cookie value; the Gateway does not accept it as an Authorization bearer.")
    expires_in: int = Field(description="access_token lifetime in seconds")
    login_ticket: str = Field(description="One-time ticket, already embedded in login_url")
    login_url: str = Field(description="Send the browser here to land signed in")


def _live_config() -> ExternalUserAuthConfig:
    from deerflow.config.app_config import get_app_config

    return get_app_config().auth.external_user


async def _config() -> ExternalUserAuthConfig:
    """The live ``auth.external_user`` config, read off the event loop.

    Both routes are unauthenticated, and ``get_app_config`` stats and re-hashes
    the config files on every call — the same rule the other public auth routes
    follow (``tests/blocking_io/test_auth_router_config_reads.py``).
    """
    return await asyncio.to_thread(_live_config)


def _require_enabled(config: ExternalUserAuthConfig) -> None:
    if not config.enabled:
        # 404 rather than 403: a disabled feature is not discoverable.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External user provisioning is not enabled")


def _verify_api_key(request: Request, config: ExternalUserAuthConfig) -> None:
    """Constant-time check of the shared key from either accepted carrier."""
    presented = request.headers.get(EXTERNAL_USER_KEY_HEADER)
    if not presented:
        authorization = request.headers.get("authorization")
        if authorization is not None:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() == "bearer":
                presented = value.strip()
    if not presented or not constant_time_equals(presented, config.api_key or ""):
        # One generic verdict, so the endpoint is not a key-validity oracle.
        logger.warning("Rejected an external provisioning call from %s: bad or missing API key", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def _session_expiry(config: ExternalUserAuthConfig) -> timedelta:
    if config.session_expiry_minutes is not None:
        return timedelta(minutes=config.session_expiry_minutes)
    return timedelta(days=get_auth_config().token_expiry_days)


def _public_origin(request: Request) -> str:
    """Proxy-aware origin of this Gateway, for the browser-facing login URL."""
    origin = _request_origin(request)
    if not origin:
        origin = f"{request.url.scheme}://{request.headers.get('host', 'localhost:8001')}"
    return origin.rstrip("/")


async def _store_username(user_id: str, username: str) -> None:
    """Persist the external display name; best effort, never fatal.

    The account is already usable without it, and a preferences write must not
    turn a successful provision into a 500.
    """

    def _write() -> None:
        from deerflow.persistence.engine import get_session_factory
        from deerflow.persistence.user.preferences import UserPreferencesRepository

        sessions = get_session_factory()
        if sessions is None:
            raise RuntimeError("no SQL session factory configured")
        return UserPreferencesRepository(sessions)

    try:
        repository = await asyncio.to_thread(_write)
        await repository.patch(user_id, {EXTERNAL_USERNAME_PREFERENCE_KEY: username})
    except Exception:
        logger.warning("Could not store the external display name for user %s", user_id, exc_info=True)


@router.post("/provision", response_model=ExternalProvisionResponse)
async def provision_external_user(request: Request, body: ExternalProvisionRequest) -> ExternalProvisionResponse:
    """Resolve or register the account for a phone number and return its credentials."""
    config = await _config()
    _require_enabled(config)
    _verify_api_key(request, config)

    phone = normalize_phone(body.phone)
    username = normalize_username(body.username)
    next_path = validate_next_param(body.next)

    result = await get_or_provision_external_user(phone=phone, config=config, local_provider=get_local_provider())
    user = result["user"]
    user_id = str(user.id)

    expiry = _session_expiry(config)
    access_token = create_access_token(user_id, expires_delta=expiry, token_version=user.token_version)
    ticket = create_external_login_ticket(user_id, ttl_seconds=config.ticket_ttl_seconds, next_path=next_path)

    login_url = f"{_public_origin(request)}/api/v1/auth/external/login?ticket={urllib.parse.quote(ticket)}"
    if next_path:
        login_url += f"&next={urllib.parse.quote(next_path)}"

    if username:
        await _store_username(user_id, username)

    logger.info(
        "External provisioning %s user_id=%s role=%s (created=%s)",
        "registered" if result["created"] else "resolved",
        user_id,
        user.system_role,
        result["created"],
    )
    return ExternalProvisionResponse(
        user_id=user_id,
        phone=phone,
        username=username or None,
        email=user.email,
        system_role=user.system_role,
        created=bool(result["created"]),
        access_token=access_token,
        expires_in=int(expiry.total_seconds()),
        login_ticket=ticket,
        login_url=login_url,
    )


@router.get("/login")
async def external_login(
    request: Request,
    ticket: str | None = None,
    next_path: str | None = Query(default=None, alias="next"),
) -> Response:
    """Redeem a one-time ticket: set the session cookies and land in the UI.

    Every failure redirects to the login page with a generic error code rather
    than raising, so a browser never sees a JSON error and the endpoint is not a
    ticket-validity oracle.
    """
    config = await _config()
    frontend_base = (config.frontend_base_url or "").rstrip("/")
    failure = RedirectResponse(url=f"{frontend_base}{_LOGIN_ERROR_PATH}", status_code=status.HTTP_302_FOUND)
    if not config.enabled:
        return failure

    payload = consume_external_login_ticket(ticket) if ticket else None
    if payload is None:
        return failure

    user = await get_local_provider().get_user(payload.uid)
    if user is None or getattr(user, "disabled", False):
        logger.warning("External login ticket named an unusable account (user=%s)", payload.uid)
        return failure

    redirect_target = validate_next_param(next_path) or validate_next_param(payload.next_path) or "/workspace"
    response = RedirectResponse(
        url=f"{frontend_base}/auth/callback?next={urllib.parse.quote(redirect_target)}",
        status_code=status.HTTP_302_FOUND,
    )
    token = create_access_token(str(user.id), token_version=user.token_version)
    set_session_cookie(response, request, token, remember_me=True)

    # A GET never passes through the CSRF middleware's cookie issuance, so the
    # double-submit pair is completed here exactly as the OIDC callback does.
    secure, max_age = auth_csrf_cookie_settings(request)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=generate_csrf_token(),
        httponly=False,  # JS-readable by design: double-submit cookie pattern
        secure=secure,
        samesite="strict",
        max_age=max_age,
    )
    logger.info("External login ticket redeemed for user_id=%s", user.id)
    return response
