"""Provisioning DeerFlow accounts from an external phone-based user system.

Mirrors :mod:`app.gateway.auth.user_provisioning` (the OIDC path) with one
difference in emphasis: the caller is a trusted operator service, not an identity
provider the user chose, so the phone number *is* the identity and there is no
email to verify.

Identity mapping reuses the existing external-identity columns rather than adding
a schema:

- ``users.oauth_provider`` = ``auth.external_user.provider_id``
- ``users.oauth_id``       = the normalized phone number

That pair carries a partial unique index, so two concurrent provisions of one
phone converge on one row: the loser's insert raises ``ValueError`` and is
resolved by a re-read instead of surfacing a 500 or creating a duplicate.

``users.email`` is NOT NULL and unique but an external phone user has none, so a
reserved synthetic address (``{phone}@{email_domain}``) is derived from the phone.
It is a storage key, never a deliverable address. As in the OIDC path, an account
that already owns that email without carrying this provider link is a 409 — an
external provisioning call must never seize a pre-existing local account.

Created rows have ``password_hash = None``, so password login stays impossible
for them; the external system owns their authentication.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from fastapi import HTTPException, status

from app.gateway.auth.local_provider import LocalAuthProvider
from deerflow.config.auth_config import ExternalUserAuthConfig

logger = logging.getLogger(__name__)

#: Digits with an optional leading ``+`` after separators are stripped.
_PHONE_PATTERN = re.compile(r"^\+?[0-9]{5,20}$")
_PHONE_SEPARATORS_RE = re.compile(r"[\s\-().]+")
#: Display-name bound, matching ``AgentConfig.display_name``'s 100 code points.
USERNAME_MAX_CHARS = 100
#: C0/C1 controls and the bidirectional formatting block: a username is rendered
#: in the UI and stored in JSON, so invisible direction overrides are rejected
#: rather than sanitized silently.
_USERNAME_FORBIDDEN_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\u200b\u200e\u200f\u2028\u2029\u2060-\u2065\ufeff]")


def normalize_phone(raw: object) -> str:
    """Normalize an externally supplied phone number, or raise 422.

    Only presentation separators (spaces, dashes, dots, parentheses) are removed;
    the digits and an optional leading ``+`` must survive unchanged, because the
    result is the identity key. Normalizing NFC first keeps full-width digits from
    an IME from becoming a second identity for one person.
    """
    if not isinstance(raw, str):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="phone must be a string")
    candidate = _PHONE_SEPARATORS_RE.sub("", unicodedata.normalize("NFKC", raw.strip()))
    if not _PHONE_PATTERN.fullmatch(candidate):
        # The raw value is not logged: a phone number is personal data, and the
        # caller already knows what it sent.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="phone must be 5-20 digits with an optional leading +",
        )
    return candidate


def normalize_username(raw: object) -> str:
    """Normalize the optional display name, or raise 422. Returns "" when absent."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="username must be a string")
    candidate = raw.strip()
    if not candidate:
        return ""
    if _USERNAME_FORBIDDEN_RE.search(candidate):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="username must not contain control or bidirectional formatting characters",
        )
    if len(candidate) > USERNAME_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"username must be at most {USERNAME_MAX_CHARS} characters",
        )
    return candidate


def derive_email(phone: str, email_domain: str) -> str:
    """The reserved synthetic address that satisfies ``users.email``."""
    return f"{phone.lstrip('+')}@{email_domain}"


def resolve_role(phone: str, config: ExternalUserAuthConfig) -> str:
    """``admin`` for a listed phone, otherwise the configured default role."""
    listed = {normalize_admin_phone(entry) for entry in config.admin_phones}
    return "admin" if phone in listed else config.default_role


def normalize_admin_phone(raw: str) -> str:
    """Normalize a configured admin phone without raising on a bad entry."""
    candidate = _PHONE_SEPARATORS_RE.sub("", unicodedata.normalize("NFKC", str(raw).strip()))
    return candidate if _PHONE_PATTERN.fullmatch(candidate) else ""


async def get_or_provision_external_user(
    *,
    phone: str,
    config: ExternalUserAuthConfig,
    local_provider: LocalAuthProvider,
) -> dict:
    """Resolve the account for ``phone``, creating it on first sight.

    Returns ``{"user": User, "created": bool}``. Raises :class:`HTTPException`
    for a disabled account (403) or an email owned by an unrelated account (409).
    """
    existing = await local_provider.get_user_by_oauth(config.provider_id, phone)
    if existing is not None:
        if getattr(existing, "disabled", False):
            # Same posture as password login and OIDC: the row is kept so
            # re-enabling restores exactly what was suspended.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account has been disabled. Please contact your administrator.",
            )
        return {"user": existing, "created": False}

    email = derive_email(phone, config.email_domain)
    owner = await local_provider.get_user_by_email(email)
    if owner is not None:
        # A row already holds the derived address. Only the exact same external
        # identity may reuse it; anything else is a collision we must not paper
        # over by linking (that would hand this caller someone else's account).
        if getattr(owner, "oauth_provider", None) == config.provider_id and getattr(owner, "oauth_id", None) == phone:
            if getattr(owner, "disabled", False):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This account has been disabled. Please contact your administrator.",
                )
            return {"user": owner, "created": False}
        logger.warning("External provisioning refused: %s is owned by another account", email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An unrelated account already owns the derived email for this phone number.",
        )

    role = resolve_role(phone, config)
    try:
        user = await local_provider.create_oauth_user(
            email=email,
            oauth_provider=config.provider_id,
            oauth_id=phone,
            system_role=role,
        )
    except ValueError:
        # Lost a race with a concurrent provision of the same phone: the winner's
        # row is the answer. Anything else means the derived email now belongs to
        # a different account.
        raced = await local_provider.get_user_by_oauth(config.provider_id, phone)
        if raced is not None:
            return {"user": raced, "created": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An unrelated account already owns the derived email for this phone number.",
        ) from None
    logger.info("Provisioned external user %s (provider=%s, role=%s)", email, config.provider_id, role)
    return {"user": user, "created": True}
