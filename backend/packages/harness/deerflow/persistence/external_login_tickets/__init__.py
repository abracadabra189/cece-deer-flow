"""Durable single-use consumption records for external login tickets."""

from __future__ import annotations

from deerflow.persistence.external_login_tickets.model import ExternalLoginTicketRow
from deerflow.persistence.external_login_tickets.sql import SqlExternalLoginTicketStore

__all__ = ["ExternalLoginTicketRow", "SqlExternalLoginTicketStore", "resolve_ticket_store"]


def resolve_ticket_store() -> SqlExternalLoginTicketStore | None:
    """The SQL ticket store for the live engine, or ``None`` without one.

    ``None`` means the deployment has no application database — which also means
    it has no ``users`` table, so external provisioning cannot work at all. The
    caller rejects the ticket rather than falling back to a process-local record.
    """
    from deerflow.persistence.engine import get_session_factory

    sessions = get_session_factory()
    if sessions is None:
        return None
    return SqlExternalLoginTicketStore(sessions)
