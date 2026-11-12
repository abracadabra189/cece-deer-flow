"""OIDC / SSO authentication configuration models."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from deerflow.config.reload_boundary import format_field_description

#: ``users.oauth_provider`` column width — the external provider id must fit it.
_EXTERNAL_PROVIDER_ID_MAX_CHARS = 32
_EXTERNAL_PROVIDER_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
#: Conservative hostname shape for the reserved synthetic-email domain.
_EXTERNAL_EMAIL_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")
#: ``users.system_role`` column width.
_EXTERNAL_ROLE_MAX_CHARS = 16
#: ``users.email`` column width; the derived address must fit it.
_EXTERNAL_EMAIL_MAX_CHARS = 320
#: Minimum shared-secret length: this key alone authorizes account creation.
_EXTERNAL_API_KEY_MIN_CHARS = 16


class OIDCProviderConfig(BaseModel):
    """Configuration for a single OIDC identity provider (Keycloak, Google, Azure AD, etc.)."""

    display_name: str = Field(description="Human-readable name shown on the login button")
    issuer: str = Field(description="OIDC issuer URL (e.g. https://keycloak.example.com/realms/deerflow)")
    client_id: str = Field(description="OAuth2 client ID assigned by the provider")
    client_secret: str | None = Field(default=None, description="OAuth2 client secret ($ENV_VAR references supported)")
    redirect_uri: str | None = Field(default=None, description="Callback URL the provider will redirect to after auth")
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="OIDC scopes to request (must include openid)",
    )
    token_endpoint_auth_method: Literal["client_secret_post", "client_secret_basic", "none"] = Field(
        default="client_secret_post",
        description="How the client authenticates at the token endpoint",
    )

    # ── User provisioning ─────────────────────────────────────────────
    auto_create_users: bool = Field(
        default=True,
        description="Automatically create a DeerFlow user on first SSO login",
    )
    require_verified_email: bool = Field(
        default=True,
        description="Reject authentication if the provider does not report the email as verified",
    )
    allowed_email_domains: list[str] = Field(
        default_factory=list,
        description="If non-empty, only allow users whose email domain is in this list (e.g. ['example.com'])",
    )
    admin_emails: list[str] = Field(
        default_factory=list,
        description="Users with these email addresses are automatically granted the admin role on first login",
    )

    # ── PKCE / nonce ──────────────────────────────────────────────────
    pkce_enabled: bool = Field(default=True, description="Enable PKCE (S256) for the authorization code flow")
    nonce_enabled: bool = Field(default=True, description="Include and validate the nonce claim in ID tokens")

    # ── Endpoint overrides (for providers with non-standard discovery) ─
    authorization_endpoint: str | None = Field(default=None)
    token_endpoint: str | None = Field(default=None)
    userinfo_endpoint: str | None = Field(default=None)
    jwks_uri: str | None = Field(default=None)


class OIDCAuthConfig(BaseModel):
    """Top-level OIDC authentication configuration."""

    enabled: bool = Field(default=False, description="Enable OIDC SSO authentication")
    frontend_base_url: str | None = Field(
        default=None,
        description="Base URL of the frontend (used for callback redirects when behind a reverse proxy)",
    )
    providers: dict[str, OIDCProviderConfig] = Field(
        default_factory=dict,
        description="Map of provider IDs to their configuration (e.g. keycloak, google, azure)",
    )


class LoginThrottleStorage(StrEnum):
    """Where the per-IP failed-login counter behind ``POST /api/v1/auth/login/local`` lives."""

    AUTO = "auto"
    MEMORY = "memory"
    DB = "db"


def resolve_login_throttle_storage(selector: LoginThrottleStorage | str | None, database_backend: str | None) -> Literal["memory", "db"]:
    """Resolve ``auth.local.throttle_storage`` against ``database.backend``.

    ``auto`` (the default) shares the counter through the application database
    whenever one exists (``sqlite`` or ``postgres``), so every Gateway replica
    using that database enforces one lockout per IP; a ``memory`` database has
    no shared table and falls back to the per-process counter. ``memory``
    always keeps the per-process counter. ``db`` asks for the shared table and
    degrades to ``memory`` when there is no database to hold it — the caller
    warns about that misconfiguration.
    """
    value = str(selector.value if isinstance(selector, StrEnum) else selector or LoginThrottleStorage.AUTO)
    if value == LoginThrottleStorage.MEMORY:
        return "memory"
    return "db" if database_backend in ("sqlite", "postgres") else "memory"


class LocalAuthConfig(BaseModel):
    """Configuration for the built-in email/password authentication provider."""

    allow_registration: bool = Field(
        default=True,
        description=(
            "Allow visitors to self-register a local account via POST /api/v1/auth/register. "
            "Set to false when accounts are provisioned exclusively through SSO — the OIDC "
            "provisioning policy (allowed_email_domains, require_verified_email, auto_create_users) "
            "does not apply to local registration."
        ),
    )
    max_login_attempts: int = Field(
        default=5,
        ge=2,
        description=(
            "Failed login attempts allowed from one client IP before it is locked out of "
            "POST /api/v1/auth/login/local. Defaults preserve the historical hardcoded policy. "
            "Raise it when many users share an egress IP (corporate proxy / NAT); lower it for "
            "a stricter posture. Minimum 2: one failed attempt must never lock an IP, or a "
            "single typo would block everyone behind a shared egress — the strictest legal "
            "value locks after the second failure. Where the counter lives is decided by "
            "throttle_storage: shared through the application database (the default whenever "
            "one exists) every Gateway replica enforces one limit per IP; the in-process "
            "counter is per worker, so effective attempts scale with the worker count."
        ),
    )
    lockout_seconds: float = Field(
        default=300.0,
        gt=0,
        allow_inf_nan=False,
        description=("Seconds an IP stays locked out after reaching auth.local.max_login_attempts. Defaults preserve the historical hardcoded policy (5 minutes)."),
    )
    throttle_storage: LoginThrottleStorage = Field(
        default=LoginThrottleStorage.AUTO,
        description=format_field_description(
            "auth.local.throttle_storage",
            field_doc=(
                "Where failed-login counters and lockouts for POST /api/v1/auth/login/local are kept. "
                "'auto' uses the application database whenever database.backend is sqlite or postgres, so every "
                "Gateway replica sharing that database enforces one lockout per client IP; with database.backend=memory "
                "it falls back to an in-process counter. 'memory' forces the in-process counter (per process: N replicas "
                "give an attacker N x max_login_attempts guesses and a lockout on one replica is invisible to the others). "
                "'db' forces the shared table: it falls back to memory with a warning when the database backend is memory, and refuses to start when the configured "
                "database's engine is unavailable."
            ),
        ),
    )


class ExternalUserAuthConfig(BaseModel):
    """Trusted server-to-server provisioning from an operator's existing user system.

    ``POST /api/v1/auth/external/provision`` takes a phone number plus a display
    name, resolves or creates the DeerFlow account, and returns credentials the
    caller can use to land that user in the UI already signed in.

    **Trust boundary.** The shared ``api_key`` is the *only* proof the caller
    offers, and it is worth an account for any phone number: whoever holds it can
    mint a session for anyone. Treat it like an admin credential — keep it in the
    environment (``api_key: $EXTERNAL_USER_API_KEY``), never in a tracked file,
    expose the endpoint only on a trusted network or behind TLS, and rotate it by
    changing the environment value. Enabled without a key is rejected at config
    load so the endpoint can never come up unauthenticated.

    Identity mapping reuses the existing external-identity columns: the account is
    linked as ``(oauth_provider=provider_id, oauth_id=phone)``, whose partial
    unique index makes concurrent provisioning of one phone converge on one row.
    ``users.email`` is NOT NULL and unique, so a reserved synthetic address
    (``{phone}@{email_domain}``) is derived from the phone; it is a storage key,
    never a deliverable address, and an unrelated account already owning it is a
    409 rather than a silent takeover — the same rule the OIDC provisioning
    follows. Accounts created here have no password, so password login stays
    impossible for them.
    """

    enabled: bool = Field(default=False, description="Expose the external provisioning + ticket-login endpoints")
    api_key: str | None = Field(
        default=None,
        description=(f"Shared secret every provisioning call must present ($ENV_VAR references supported). Required when enabled, at least {_EXTERNAL_API_KEY_MIN_CHARS} characters."),
    )
    provider_id: str = Field(
        default="external-phone",
        description=("Identity-provider label stored in users.oauth_provider for phone-provisioned accounts. hyphen-case, at most 32 characters. Change it only to keep several external user systems apart."),
    )
    email_domain: str = Field(
        default="users.deerflow.internal",
        description="Reserved domain for the synthetic users.email derived from the phone number. Must not be a domain you send mail to.",
    )
    default_role: str = Field(default="user", description="System role granted to newly provisioned accounts")
    admin_phones: list[str] = Field(
        default_factory=list,
        description="Phone numbers provisioned as admin instead of default_role (matched after normalization)",
    )
    ticket_ttl_seconds: int = Field(
        default=120,
        ge=10,
        le=900,
        description="Lifetime of the one-time browser login ticket. Short on purpose: it travels in a URL.",
    )
    session_expiry_minutes: int | None = Field(
        default=None,
        ge=1,
        description="Override the issued session token lifetime; null uses auth token_expiry_days",
    )
    frontend_base_url: str | None = Field(
        default=None,
        description="Frontend origin used for the post-login redirect (same meaning as auth.oidc.frontend_base_url)",
    )

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("provider_id")
    @classmethod
    def _validate_provider_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EXTERNAL_PROVIDER_ID_RE.fullmatch(normalized):
            raise ValueError(f"auth.external_user.provider_id must be hyphen-case [a-z0-9-], got {value!r}")
        if len(normalized) > _EXTERNAL_PROVIDER_ID_MAX_CHARS:
            raise ValueError(f"auth.external_user.provider_id must be at most {_EXTERNAL_PROVIDER_ID_MAX_CHARS} characters")
        return normalized

    @field_validator("email_domain")
    @classmethod
    def _validate_email_domain(cls, value: str) -> str:
        normalized = value.strip().lower().removeprefix(".")
        if not _EXTERNAL_EMAIL_DOMAIN_RE.fullmatch(normalized):
            raise ValueError(f"auth.external_user.email_domain must be a dotted hostname, got {value!r}")
        return normalized

    @field_validator("default_role")
    @classmethod
    def _validate_default_role(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > _EXTERNAL_ROLE_MAX_CHARS:
            raise ValueError(f"auth.external_user.default_role must be 1-{_EXTERNAL_ROLE_MAX_CHARS} characters")
        return normalized

    @field_validator("frontend_base_url")
    @classmethod
    def _validate_frontend_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().rstrip("/") or None

    @field_validator("admin_phones")
    @classmethod
    def _validate_admin_phones(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for entry in value:
            if not isinstance(entry, str):
                continue
            stripped = entry.strip()
            if stripped and stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned

    @model_validator(mode="after")
    def _validate_enabled_requirements(self) -> ExternalUserAuthConfig:
        """Fail closed: an enabled endpoint without a strong key is an open door."""
        if not self.enabled:
            return self
        if not self.api_key:
            raise ValueError("auth.external_user.api_key is required when auth.external_user.enabled is true (set it via $ENV_VAR)")
        if len(self.api_key) < _EXTERNAL_API_KEY_MIN_CHARS:
            raise ValueError(f"auth.external_user.api_key must be at least {_EXTERNAL_API_KEY_MIN_CHARS} characters")
        # The derived address has to fit the column it is stored in.
        longest_phone = max((len(phone) for phone in self.admin_phones), default=20)
        if longest_phone + 1 + len(self.email_domain) > _EXTERNAL_EMAIL_MAX_CHARS:
            raise ValueError("auth.external_user.email_domain is too long for the derived users.email column")
        return self


class AuthAppConfig(BaseModel):
    """Authentication configuration section for the DeerFlow app config."""

    oidc: OIDCAuthConfig = Field(default_factory=OIDCAuthConfig, description="OIDC SSO authentication settings")
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig, description="Built-in email/password authentication settings")
    external_user: ExternalUserAuthConfig = Field(
        default_factory=ExternalUserAuthConfig,
        description="Trusted phone-based provisioning from an existing external user system",
    )
