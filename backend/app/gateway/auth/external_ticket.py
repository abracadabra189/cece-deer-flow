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

**Single use, bounded by TTL.** Consumption is recorded by ``jti`` in a
process-local, expiry-pruned cache, so one ticket cannot be redeemed twice on the
same worker. There is deliberately no shared store for this: with
``GATEWAY_WORKERS > 1`` the guarantee degrades to once-per-worker, and the short
TTL (``auth.external_user.ticket_ttl_seconds``, default 2 minutes) is what
actually bounds replay — the same trade-off the OIDC state cookie makes by being
stateless. Tickets are signed with ``AUTH_JWT_SECRET``.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import OrderedDict

import jwt
from pydantic import BaseModel, ValidationError

from app.gateway.auth.config import get_auth_config

logger = logging.getLogger(__name__)

#: Claim that separates this credential from every other JWT the Gateway signs.
TICKET_PURPOSE = "external_user_login"
#: Bound on the consumed-jti cache; expired entries are pruned on every insert.
_CONSUMED_MAX_ENTRIES = 4096

_consumed_lock = threading.Lock()
_consumed_jti: OrderedDict[str, float] = OrderedDict()


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


def _remember_consumed(jti: str, expires_at: float) -> bool:
    """Record ``jti`` as spent; return False when it was already spent."""
    now = time.time()
    with _consumed_lock:
        while _consumed_jti:
            oldest_jti, oldest_expiry = next(iter(_consumed_jti.items()))
            if oldest_expiry <= now:
                _consumed_jti.popitem(last=False)
                continue
            break
        if jti in _consumed_jti:
            return False
        _consumed_jti[jti] = max(expires_at, now + 1.0)
        while len(_consumed_jti) > _CONSUMED_MAX_ENTRIES:
            _consumed_jti.popitem(last=True)
        return True


def consume_external_login_ticket(token: str) -> ExternalLoginTicket | None:
    """Verify and spend a ticket, returning ``None`` for any failure.

    One generic failure surface (mirroring ``authenticate_pat``): an expired,
    tampered, replayed, wrong-purpose or malformed ticket is indistinguishable
    from the outside, so the endpoint cannot be used to probe ticket validity.
    """
    if not isinstance(token, str) or not token.strip():
        return None
    try:
        decoded = jwt.decode(token.strip(), get_auth_config().jwt_secret, algorithms=["HS256"])
        ticket = ExternalLoginTicket(**decoded)
    except (jwt.PyJWTError, ValidationError, ValueError):
        return None
    if ticket.purpose != TICKET_PURPOSE or not ticket.uid:
        return None
    if not _remember_consumed(ticket.jti, float(ticket.exp)):
        logger.info("Rejected a replayed external login ticket (user=%s)", ticket.uid)
        return None
    return ticket


def reset_consumed_tickets() -> None:
    """Drop the consumed-jti cache. Test isolation only."""
    with _consumed_lock:
        _consumed_jti.clear()
