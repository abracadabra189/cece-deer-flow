"""Provisioning DeerFlow accounts from an external account system.

Mirrors :mod:`app.gateway.auth.user_provisioning` (the OIDC path) with one
difference in emphasis: the caller is a trusted operator service, not an identity
provider the user chose, so the external **account name** *is* the identity and
there is nothing to verify beyond the shared key.

``account`` is the identity key. It may be Chinese, numeric, or an email address,
so it is canonicalized before use (:func:`canonical_account`) rather than stored
verbatim: NFKC, trimmed, whitespace-collapsed and casefolded, because an account
system that hands us ``Zhang.San@corp.com`` and ``zhang.san@CORP.com`` means one
person, not two. A phone-shaped account is canonicalized with the phone rules
instead, which keeps identities issued before ``account`` existed resolvable.

Identity mapping reuses the existing external-identity columns rather than adding
a schema:

- ``users.oauth_provider`` = ``auth.external_user.provider_id``
- ``users.oauth_id``       = the canonical account

That pair carries a partial unique index, so two concurrent provisions of one
account converge on one row: the loser's insert raises ``ValueError`` and is
resolved by a re-read instead of surfacing a 500 or creating a duplicate.

``users.email`` is NOT NULL, unique and typed ``EmailStr``, while an external
account may be CJK or an address in another domain, so a reserved synthetic
address is derived (:func:`derive_email`): an ASCII-safe account keeps a readable
local part, anything else becomes a stable hash. It is a storage key, never a
deliverable address. As in the OIDC path, an account that already owns that email
without carrying this provider link is a 409 — an external provisioning call must
never seize a pre-existing local account.

Created rows have ``password_hash = None``, so password login stays impossible for
them; the external system owns their authentication. ``phone`` is optional contact
data, persisted as a preference by the router, and never part of the identity.
"""

from __future__ import annotations

import hashlib
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
#: ``users.oauth_id`` column width — the canonical account must fit it.
ACCOUNT_MAX_CHARS = 128
#: Display-name bound, matching ``AgentConfig.display_name``'s 100 code points.
USERNAME_MAX_CHARS = 100
#: An account that is already ASCII and email-local-part safe keeps a readable
#: derived address; anything else (CJK, an email address, punctuation) is hashed.
_SAFE_LOCAL_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
#: Hashed local part: ``u`` + this many hex chars of SHA-256 over the identity.
_HASH_LOCAL_PART_CHARS = 24
#: ``users.email`` column width.
_EMAIL_MAX_CHARS = 320
#: C0/C1 controls and the bidirectional formatting block: both the account and the
#: display name are stored in JSON and rendered in the UI, so invisible direction
#: overrides are rejected rather than sanitized silently.
_FORBIDDEN_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\u200b\u200e\u200f\u2028\u2029\u2060-\u2065\ufeff]")
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _reject(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def normalize_account(raw: object) -> str:
    """Normalize an externally supplied account name into its display form.

    NFKC first so full-width digits or compatibility characters from an IME cannot
    become a second identity for one account, then trim. Casing and interior
    spacing are preserved here — this is the value shown to humans and stored as
    the account preference; :func:`canonical_account` derives the identity form.
    """
    if raw is None or not isinstance(raw, str):
        raise _reject("account must be a non-empty string")
    candidate = unicodedata.normalize("NFKC", raw).strip()
    if not candidate:
        raise _reject("account must be a non-empty string")
    if _FORBIDDEN_CHARS_RE.search(candidate):
        # Not logged: an account name may be an email address or a person's name.
        raise _reject("account must not contain control or bidirectional formatting characters")
    if len(candidate) > ACCOUNT_MAX_CHARS:
        raise _reject(f"account must be at most {ACCOUNT_MAX_CHARS} characters")
    return candidate


def canonical_account(raw: object) -> str:
    """The identity form of an account name: what ``users.oauth_id`` stores.

    A phone-shaped account is canonicalized with the phone rules, so
    ``+86 138-0000-5555``, ``(+86)13800005555`` and ``+8613800005555`` are one
    identity — and identities issued while the phone number *was* the key stay
    resolvable. Any other account is whitespace-collapsed and casefolded, because
    login names and email addresses are conventionally case-insensitive.
    """
    display = normalize_account(raw)
    phone_shaped = _PHONE_SEPARATORS_RE.sub("", display)
    if _PHONE_PATTERN.fullmatch(phone_shaped):
        return phone_shaped
    return _WHITESPACE_RUN_RE.sub(" ", display).casefold()


def normalize_phone(raw: object) -> str:
    """Normalize an optional phone number, or raise 422. Returns "" when absent.

    Only presentation separators (spaces, dashes, dots, parentheses) are removed;
    the digits and an optional leading ``+`` survive unchanged.
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise _reject("phone must be a string")
    candidate = _PHONE_SEPARATORS_RE.sub("", unicodedata.normalize("NFKC", raw.strip()))
    if not candidate:
        return ""
    if not _PHONE_PATTERN.fullmatch(candidate):
        raise _reject("phone must be 5-20 digits with an optional leading +")
    return candidate


def normalize_username(raw: object) -> str:
    """Normalize the optional display name, or raise 422. Returns "" when absent."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise _reject("username must be a string")
    candidate = unicodedata.normalize("NFKC", raw).strip()
    if not candidate:
        return ""
    if _FORBIDDEN_CHARS_RE.search(candidate):
        raise _reject("username must not contain control or bidirectional formatting characters")
    if len(candidate) > USERNAME_MAX_CHARS:
        raise _reject(f"username must be at most {USERNAME_MAX_CHARS} characters")
    return candidate


def derive_email(identity: str, email_domain: str) -> str:
    """The reserved synthetic address that satisfies ``users.email``.

    Readable when the identity already is an ASCII email-local-part shape (digits,
    latin names — including a phone identity, whose leading ``+`` is dropped so the
    address matches what phone-keyed provisioning used to derive); a stable hash
    otherwise, because a CJK name or a foreign email address cannot be a local part
    here. The hash is over the canonical identity, so one account always maps to
    one address. An oversized result falls back to the hash to stay within the
    column.
    """
    local = identity.lstrip("+")
    if not _SAFE_LOCAL_PART_RE.fullmatch(local) or len(local) + 1 + len(email_domain) > _EMAIL_MAX_CHARS:
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:_HASH_LOCAL_PART_CHARS]
        local = f"u{digest}"
    return f"{local}@{email_domain}"


def resolve_role(*, identity: str, phone: str, config: ExternalUserAuthConfig) -> str:
    """``admin`` for a listed account or phone, otherwise the configured default.

    ``admin_phones`` predates the account-based identity and keeps its name; entries
    are matched in canonical form, so it accepts phone numbers and account names
    alike.
    """
    listed = {canonical_identity_or_empty(entry) for entry in config.admin_phones}
    listed.discard("")
    if identity in listed or (phone and phone in listed):
        return "admin"
    return config.default_role


def canonical_identity_or_empty(raw: object) -> str:
    """Canonicalize a configured admin entry without raising on a bad value."""
    try:
        return canonical_account(raw)
    except HTTPException:
        return ""


async def get_or_provision_external_user(
    *,
    identity: str,
    config: ExternalUserAuthConfig,
    local_provider: LocalAuthProvider,
    phone: str = "",
) -> dict:
    """Resolve the account for a canonical identity, creating it on first sight.

    ``phone`` takes part in the admin-list match only; it is never part of the
    identity. Returns ``{"user": User, "created": bool}``. Raises
    :class:`HTTPException` for a disabled account (403) or an email owned by an
    unrelated account (409).
    """
    existing = await local_provider.get_user_by_oauth(config.provider_id, identity)
    if existing is not None:
        if getattr(existing, "disabled", False):
            # Same posture as password login and OIDC: the row is kept so
            # re-enabling restores exactly what was suspended.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account has been disabled. Please contact your administrator.",
            )
        return {"user": existing, "created": False}

    email = derive_email(identity, config.email_domain)
    owner = await local_provider.get_user_by_email(email)
    if owner is not None:
        # A row already holds the derived address. Only the exact same external
        # identity may reuse it; anything else is a collision we must not paper
        # over by linking (that would hand this caller someone else's account).
        if getattr(owner, "oauth_provider", None) == config.provider_id and getattr(owner, "oauth_id", None) == identity:
            if getattr(owner, "disabled", False):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This account has been disabled. Please contact your administrator.",
                )
            return {"user": owner, "created": False}
        logger.warning("External provisioning refused: the derived email for one account is owned by another")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An unrelated account already owns the derived email for this account name.",
        )

    role = resolve_role(identity=identity, phone=phone, config=config)
    try:
        user = await local_provider.create_oauth_user(
            email=email,
            oauth_provider=config.provider_id,
            oauth_id=identity,
            system_role=role,
        )
    except ValueError:
        # Lost a race with a concurrent provision of the same account: the winner's
        # row is the answer. Anything else means the derived email now belongs to a
        # different account.
        raced = await local_provider.get_user_by_oauth(config.provider_id, identity)
        if raced is not None:
            return {"user": raced, "created": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An unrelated account already owns the derived email for this account name.",
        ) from None
    logger.info("Provisioned external user %s (provider=%s, role=%s)", user.id, config.provider_id, role)
    return {"user": user, "created": True}
