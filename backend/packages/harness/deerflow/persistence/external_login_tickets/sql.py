"""SQL-backed single-use consumption of external login tickets.

The Gateway may run several uvicorn workers, and a deployment may run several
Gateway replicas behind one load balancer. A process-local "already used" set
would let the same ticket be redeemed once per process — a replay window that
only shows up in production. This store puts the guarantee where the users table
already lives: the application database.

Concurrency contract (the same shape ``login_throttle`` uses):

- ``claim`` is one dialect-native ``INSERT ... ON CONFLICT (jti) DO NOTHING``.
  The primary key makes two racing claims mutually exclusive and the statement's
  affected-row count says who won: ``1`` for the winner, ``0`` when a peer (or an
  earlier request in this process) already spent it. There is no read-then-write
  window to lose a race in.
- Expired-row cleanup rides in the claim's own transaction — one commit per
  redemption, not two — bounded by :data:`SWEEP_BATCH_SIZE` and excluding the row
  just claimed. The expiry predicate appears both in the ``IN (SELECT ... LIMIT
  n)`` subquery and on the ``DELETE`` target, because PostgreSQL READ COMMITTED
  re-evaluates only the outer WHERE on a row it had to wait for.
- Database errors propagate. The caller rejects the ticket: without a claim there
  is no proof of single use, and failing open would silently restore the replay
  window this module exists to close.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.external_login_tickets.model import ExternalLoginTicketRow

logger = logging.getLogger(__name__)

#: Rows one claim may delete; bounds the write transaction when a backlog exists.
SWEEP_BATCH_SIZE = 200


def _insert_for(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert
    if dialect == "sqlite":
        return sqlite_insert
    raise ValueError(f"Unsupported external login ticket database dialect: {dialect}")


def _timestamp(now: float) -> datetime:
    return datetime.fromtimestamp(now, UTC)


class SqlExternalLoginTicketStore:
    """Persistence facade for ``external_login_tickets``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def claim(self, jti: str, *, user_id: str, expires_at: datetime, now: float | None = None) -> bool:
        """Atomically spend ``jti``; ``True`` for the winner, ``False`` when already spent.

        ``expires_at`` is the ticket's own expiry, so the row outlives exactly as
        long as the signed token could still verify.
        """
        stamp = _timestamp(time.time() if now is None else now)
        async with self._sf() as session:
            insert = _insert_for(session)
            statement = insert(ExternalLoginTicketRow).values(jti=jti, user_id=user_id, consumed_at=stamp, expires_at=expires_at).on_conflict_do_nothing(index_elements=[ExternalLoginTicketRow.jti])
            result = await session.execute(statement)
            claimed = result.rowcount == 1
            # Housekeeping shares this transaction; never sweep the row just claimed.
            await session.execute(self.sweep_statement(stamp.timestamp(), keep=jti))
            await session.commit()
        return claimed

    async def sweep(self, *, now: float | None = None) -> int:
        """Delete expired rows, bounded by :data:`SWEEP_BATCH_SIZE`; returns the count."""
        stamp = time.time() if now is None else now
        async with self._sf() as session:
            result = await session.execute(self.sweep_statement(stamp))
            await session.commit()
        return int(result.rowcount or 0)

    async def is_spent(self, jti: str) -> bool:
        """Whether ``jti`` has a consumption row. Diagnostics and tests."""
        async with self._sf() as session:
            row = (await session.execute(select(ExternalLoginTicketRow.jti).where(ExternalLoginTicketRow.jti == jti))).first()
            await session.rollback()
        return row is not None

    @staticmethod
    def sweep_statement(now: float, *, keep: str | None = None):
        """The bounded cleanup ``DELETE`` (see the module docstring).

        ``keep`` is the jti the calling ``claim`` just inserted: its expiry is in
        the future by construction, but excluding it keeps the sweep from ever
        touching the row whose claim is being decided in the same transaction.
        """
        expired = ExternalLoginTicketRow.expires_at <= _timestamp(now)
        candidates = select(ExternalLoginTicketRow.jti).where(expired if keep is None else and_(ExternalLoginTicketRow.jti != keep, expired)).limit(SWEEP_BATCH_SIZE)
        target = expired if keep is None else and_(ExternalLoginTicketRow.jti != keep, expired)
        return delete(ExternalLoginTicketRow).where(ExternalLoginTicketRow.jti.in_(candidates), target)
