"""Durable single-use consumption of external login tickets.

The property that only matters in production: with several Gateway workers — or
several replicas behind one load balancer — a redeemed ticket stays redeemed
everywhere. A process-local record cannot express that, so these tests drive the
real SQL store on both supported backends, and the race is reproduced with real
independent processes rather than threads sharing a mutex.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.schema import DropSchema

from app.gateway.auth import config as auth_config_module
from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.external_ticket import consume_external_login_ticket, create_external_login_ticket
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.external_login_tickets import SqlExternalLoginTicketStore
from deerflow.persistence.external_login_tickets.model import ExternalLoginTicketRow
from deerflow.persistence.external_login_tickets.sql import SWEEP_BATCH_SIZE

_JWT_SECRET = "ticket-store-test-secret-0123456789"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fixed_jwt_secret():
    """A deterministic signing secret for ticket minting/verification."""
    previous = auth_config_module._auth_config
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))
    yield _JWT_SECRET
    auth_config_module._auth_config = previous


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def store(tmp_path, request):
    """The real store over a real engine, on SQLite and (when available) PostgreSQL."""
    config = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        config = DatabaseConfig(backend="postgres", postgres_url=uri, postgres_schema="ext_tickets_" + uuid4().hex)
    await init_engine_from_config(config)
    try:
        yield SqlExternalLoginTicketStore(get_session_factory())
    finally:
        if config.backend == "postgres":
            async with get_engine().begin() as connection:
                await connection.execute(DropSchema(config.postgres_schema, cascade=True))
        await close_engine()


def _expiry(seconds: int = 60) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


class TestClaim:
    async def test_the_first_claim_wins_and_a_replay_loses(self, store):
        assert await store.claim("jti-1", user_id="user-1", expires_at=_expiry()) is True
        assert await store.claim("jti-1", user_id="user-1", expires_at=_expiry()) is False

    async def test_concurrent_claims_yield_exactly_one_winner(self, store):
        """Racing redemptions of one ticket — the multi-worker replay window."""
        results = await asyncio.gather(*[store.claim("jti-race", user_id="user-1", expires_at=_expiry()) for _ in range(25)])

        assert sum(1 for claimed in results if claimed) == 1

    async def test_distinct_tickets_are_independent(self, store):
        assert await store.claim("jti-a", user_id="user-1", expires_at=_expiry()) is True
        assert await store.claim("jti-b", user_id="user-1", expires_at=_expiry()) is True

    async def test_is_spent_reflects_the_claim(self, store):
        assert await store.is_spent("jti-2") is False
        await store.claim("jti-2", user_id="user-1", expires_at=_expiry())
        assert await store.is_spent("jti-2") is True

    async def test_the_owner_is_recorded_for_audit(self, store):
        await store.claim("jti-3", user_id="user-42", expires_at=_expiry())

        async with get_session_factory()() as session:
            row = (await session.execute(select(ExternalLoginTicketRow).where(ExternalLoginTicketRow.jti == "jti-3"))).scalar_one()

        assert row.user_id == "user-42"
        assert row.consumed_at is not None


class TestSweep:
    async def _insert(self, jti: str, expires_at: datetime) -> None:
        """Seed a consumption row directly, bypassing ``claim``'s own sweep."""
        async with get_session_factory()() as session, session.begin():
            session.add(ExternalLoginTicketRow(jti=jti, user_id="user-1", consumed_at=datetime.now(UTC), expires_at=expires_at))

    async def test_expired_rows_are_swept_and_the_live_row_survives(self, store):
        await self._insert("expired-1", datetime.now(UTC) - timedelta(seconds=30))
        await self._insert("live-1", _expiry(300))

        assert await store.sweep() == 1
        assert await store.is_spent("expired-1") is False
        assert await store.is_spent("live-1") is True

    async def test_a_claim_sweeps_without_touching_its_own_row(self, store):
        await self._insert("expired-2", datetime.now(UTC) - timedelta(seconds=30))

        # The claiming ticket is itself already expired; ``keep`` must still protect
        # it, otherwise the claim would delete its own proof of consumption.
        assert await store.claim("expired-3", user_id="user-1", expires_at=datetime.now(UTC) - timedelta(seconds=1)) is True
        assert await store.is_spent("expired-3") is True
        assert await store.is_spent("expired-2") is False

    async def test_sweep_is_bounded(self, store):
        past = datetime.now(UTC) - timedelta(seconds=30)
        for index in range(SWEEP_BATCH_SIZE + 5):
            await self._insert(f"bulk-{index}", past)

        assert await store.sweep() == SWEEP_BATCH_SIZE
        # The remainder goes on a later call, so the table cannot grow unbounded.
        assert await store.sweep() == 5


class TestConsume:
    async def test_a_ticket_is_consumed_exactly_once_end_to_end(self, store):
        ticket = create_external_login_ticket("user-1", ttl_seconds=60)

        first = await consume_external_login_ticket(ticket)
        second = await consume_external_login_ticket(ticket)

        assert first is not None
        assert first.uid == "user-1"
        assert second is None

    async def test_concurrent_consumption_yields_exactly_one_ticket(self, store):
        ticket = create_external_login_ticket("user-1", ttl_seconds=60)

        results = await asyncio.gather(*[consume_external_login_ticket(ticket) for _ in range(10)])

        assert sum(1 for result in results if result is not None) == 1

    async def test_consume_fails_closed_without_a_session_factory(self, monkeypatch):
        """No database means no proof of single use, so the ticket is rejected."""
        monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: None)
        ticket = create_external_login_ticket("user-1", ttl_seconds=60)

        assert await consume_external_login_ticket(ticket) is None

    async def test_consume_fails_closed_when_the_claim_raises(self, store, monkeypatch):
        async def _boom(*args, **kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(SqlExternalLoginTicketStore, "claim", _boom)
        ticket = create_external_login_ticket("user-1", ttl_seconds=60)

        assert await consume_external_login_ticket(ticket) is None

    async def test_an_unverified_ticket_never_reaches_the_store(self, store, monkeypatch):
        calls = {"n": 0}

        async def _counting_claim(self, *args, **kwargs):
            calls["n"] += 1
            return True

        monkeypatch.setattr(SqlExternalLoginTicketStore, "claim", _counting_claim)

        assert await consume_external_login_ticket("not-a-ticket") is None
        assert calls["n"] == 0


def _claim_in_child(db_dir: str, jti: str, user_id: str, expires_iso: str, queue) -> None:
    """Child process body: one independent worker claiming one shared ticket."""
    from datetime import datetime as _datetime

    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.external_login_tickets import SqlExternalLoginTicketStore

    async def _run() -> bool:
        await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=db_dir))
        try:
            return await SqlExternalLoginTicketStore(get_session_factory()).claim(jti, user_id=user_id, expires_at=_datetime.fromisoformat(expires_iso))
        finally:
            await close_engine()

    queue.put(asyncio.run(_run()))


def test_independent_processes_cannot_both_spend_one_ticket(tmp_path):
    """The production shape: separate Gateway processes, one shared database.

    A process-local consumed-set would let every worker redeem the same ticket
    once; the primary key on ``jti`` makes exactly one INSERT win.
    """
    db_dir = str(tmp_path)
    jti = "shared-jti"
    expires_at = _expiry(300).isoformat()

    async def _bootstrap() -> None:
        await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=db_dir))
        await close_engine()

    asyncio.run(_bootstrap())

    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [context.Process(target=_claim_in_child, args=(db_dir, jti, "user-1", expires_at, queue), daemon=True) for _ in range(3)]
    try:
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=180) for _ in workers]
        for worker in workers:
            worker.join(timeout=60)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=30)

    assert sorted(results) == [False, False, True]
    assert [worker.exitcode for worker in workers] == [0, 0, 0]
