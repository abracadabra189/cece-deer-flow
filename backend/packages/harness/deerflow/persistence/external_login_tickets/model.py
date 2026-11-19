"""ORM model for consumed external login tickets (``external_login_tickets``).

One row per redeemed one-time ticket from
``POST /api/v1/auth/external/provision``. The row's primary key *is* the
single-use guarantee: claiming a ticket is an ``INSERT ... ON CONFLICT DO
NOTHING`` whose affected-row count says who won, so every Gateway worker and
every replica sharing the application database agrees on "already spent"
without any process-local state.

Rows are swept by :class:`~deerflow.persistence.external_login_tickets.sql.SqlExternalLoginTicketStore`
once the ticket's own ``exp`` has passed — after that instant the signed token
can no longer verify, so keeping the row would prove nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: ``jti`` is ``secrets.token_urlsafe(16)`` (22 characters); the bound leaves
#: room for a longer identifier without a schema change.
TICKET_JTI_LENGTH = 64
#: Matches ``users.id`` (a 36-character UUID string).
TICKET_USER_ID_LENGTH = 36


class ExternalLoginTicketRow(Base):
    __tablename__ = "external_login_tickets"

    jti: Mapped[str] = mapped_column(String(TICKET_JTI_LENGTH), nullable=False)
    #: Owner the ticket was minted for. Not a foreign key: a consumed ticket must
    #: stay provable even after the account is deleted, and the login route
    #: re-resolves the user separately.
    user_id: Mapped[str] = mapped_column(String(TICKET_USER_ID_LENGTH), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    #: The ticket's own ``exp``; drives the sweep.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("jti", name="pk_external_login_tickets"),
        # Serves the sweep's expiry predicate.
        Index("ix_external_login_tickets_expires_at", "expires_at"),
    )
