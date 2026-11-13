"""One-time browser login tickets for externally provisioned users.

The external user system calls ``POST /api/v1/auth/external/provision``
server-to-server and hands the resulting ``login_url`` to the browser. Redeeming
it sets the ordinary session cookies, so the user lands signed in without a
password and without the frontend learning anything new — the same shape as the
OIDC callback, minus the identity provider.

Two properties matter:

**A ticket is not a session token.** Claims deliberately avoid ``sub``: the
session JWT decoder (:class:`app.gateway.auth.jwt.TokenPayload`) requires it, so
a ticket that leaks can never be replayed as an ``access_token`` cookie value.
It carries ``uid`` plus a ``purpose`` the session decoder does not accept.

**Single use, enforced in the database.** Consumption is one atomic
``INSERT ... ON CONFLICT (jti) DO NOTHING`` against ``external_login_tickets``
(:mod:`deerflow.persistence.external_login_tickets`), so every uvicorn worker and
every Gateway replica sharing the application database agrees on "already spent".
A process-local record would allow one redemption per process — a replay window
that only appears once a deployment scales out — and the database is where the
``users`` row this ticket names already lives, so the guarantee adds no new
dependency. Expired rows are swept in the same transaction, bounded per claim.

Both verification and consumption **fail closed**: a store that is missing or
erroring rejects the ticket instead of waving it through, because without a
durable claim there is no proof it was not used already. Tickets are signed with
``AUTH_JWT_SECRET`` and live ``auth.external_user.ticket_ttl_seconds`` (default
120 seconds).
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import UTC, datetime

import jwt
from pydantic import BaseModel, ValidationError

from app.gateway.auth.config import get_auth_config

logger = logging.getLogger(__name__)

#: Claim that separates this credential from every other JWT the Gateway signs.
TICKET_PURPOSE = "external_user_login"


class ExternalLoginTicket(BaseModel):
    """Verified ticket claims."""

    purpose: str
    #: The provisioned user's id. Not ``sub`` — see the module docstring.
    uid: str
    jti: str
    iat: float
    exp: float
    next_path: str | None = None


def create_external_login_ticket(
    user_id: str,
    *,
    ttl_seconds: int,
    next_path: str | None = None,
) -> str:
    """Mint a signed one-time login ticket for ``user_id``."""
    issued_at = int(time.time())
    payload = {
        "purpose": TICKET_PURPOSE,
        "uid": str(user_id),
        "jti": secrets.token_urlsafe(16),
        "iat": issued_at,
        "exp": issued_at + max(1, int(ttl_seconds)),
    }
    if next_path:
        payload["next_path"] = next_path
    return jwt.encode(payload, get_auth_config().jwt_secret, algorithm="HS256")


def verify_external_login_ticket(token: object) -> ExternalLoginTicket | None:
    """Check signature, purpose, required claims and expiry — **without** spending it.

    Returns ``None`` for any failure. Kept separate from :func:`consume_external_login_ticket`
    so callers that only need to inspect a ticket (and tests of the crypto half)
    do not touch the database.
    """
    if not isinstance(token, str) or not token.strip():
        return None
    try:
        decoded = jwt.decode(token.strip(), get_auth_config().jwt_secret, algorithms=["HS256"])
        ticket = ExternalLoginTicket(**decoded)
    except (jwt.PyJWTError, ValidationError, ValueError):
        return None
    if ticket.purpose != TICKET_PURPOSE or not ticket.uid or not ticket.jti:
        return None
    return ticket


async def consume_external_login_ticket(token: object) -> ExternalLoginTicket | None:
    """Verify a ticket and durably record its consumption; ``None`` on any failure.

    One generic failure surface (mirroring ``authenticate_pat``): an expired,
    tampered, replayed, wrong-purpose, malformed ticket — or a database that
    cannot record the claim — is indistinguishable from the outside, so the
    endpoint cannot be used to probe ticket validity.
    """
    ticket = verify_external_login_ticket(token)
    if ticket is None:
        return None

    from deerflow.persistence.external_login_tickets import resolve_ticket_store

    store = resolve_ticket_store()
    if store is None:
        # No application database means no users table either, so this deployment
        # cannot serve external provisioning at all; never fall back to a
        # process-local record, which is exactly the multi-worker replay window.
        logger.error("External login ticket rejected: no SQL session factory to record consumption")
        return None
    try:
        claimed = await store.claim(
            ticket.jti,
            user_id=ticket.uid,
            expires_at=datetime.fromtimestamp(float(ticket.exp), UTC),
        )
    except Exception:
        logger.warning("External login ticket claim failed; rejecting the ticket", exc_info=True)
        return None
    if not claimed:
        logger.info("Rejected a replayed external login ticket (user=%s)", ticket.uid)
        return None
    return ticket
