"""Migration 0053: the shared ``external_login_tickets`` table for durable single-use login tickets."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.external_login_tickets import ExternalLoginTicketRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0053_external_login_tickets"
PREVIOUS = "0052_batch_continuation"
TABLE = "external_login_tickets"
COLUMNS = {"jti", "user_id", "consumed_at", "expires_at"}
INDEX = "ix_external_login_tickets_expires_at"
pytestmark = pytest.mark.asyncio


async def test_0053_remains_in_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_heads() == [REVISION]
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0053)")
    schema = f"ext_tickets_{uuid.uuid4().hex}"
    return create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)), schema


async def _shape(engine) -> dict:
    async with engine.connect() as conn:

        def read(sync):
            inspector = sa.inspect(sync)
            tables = set(inspector.get_table_names())
            if TABLE not in tables:
                return {"tables": tables}
            return {
                "tables": tables,
                "columns": {col["name"]: col for col in inspector.get_columns(TABLE)},
                "pk": inspector.get_pk_constraint(TABLE)["constrained_columns"],
                "indexes": {index["name"]: index["column_names"] for index in inspector.get_indexes(TABLE)},
            }

        return await conn.run_sync(read)


async def _orm_diff(engine) -> list:
    """Alembic's own drift check, restricted to the table this revision owns."""

    def only_ticket_table(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name == TABLE
        return getattr(getattr(obj, "table", None), "name", TABLE) == TABLE

    async with engine.connect() as conn:

        def diff(sync):
            context = MigrationContext.configure(sync, opts={"include_object": only_ticket_table, "compare_type": True, "compare_server_default": True})
            return compare_metadata(context, Base.metadata)

        return await conn.run_sync(diff)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0053_creates_the_table_matching_the_orm_and_downgrades_cleanly(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        assert TABLE not in (await _shape(engine))["tables"]

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        shape = await _shape(engine)
        assert set(shape["columns"]) == COLUMNS
        assert shape["pk"] == ["jti"]
        for column in COLUMNS:
            assert shape["columns"][column]["nullable"] is False
        assert shape["indexes"][INDEX] == ["expires_at"]  # serves the sweep's expiry predicate
        # ``make migrate-rev`` would propose nothing: the revision matches the ORM model.
        assert await _orm_diff(engine) == []

        # The primary key is the single-use guarantee: a second claim of one jti must fail.
        async with engine.begin() as conn:
            await conn.execute(sa.insert(ExternalLoginTicketRow).values(jti="jti-1", user_id="user-1", consumed_at=sa.func.now(), expires_at=sa.func.now()))
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(ExternalLoginTicketRow).values(jti="jti-1", user_id="user-1", consumed_at=sa.func.now(), expires_at=sa.func.now()))
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text(f"SELECT user_id FROM {TABLE} WHERE jti='jti-1'"))).one()
        assert tuple(row) == ("user-1",)

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        shape = await _shape(engine)
        assert TABLE not in shape["tables"]
        async with engine.connect() as conn:
            # The index goes with the table on downgrade (named, so a leftover would be visible).
            leftover = await conn.run_sync(lambda sync: [name for table in sa.inspect(sync).get_table_names() for name in {index["name"] for index in sa.inspect(sync).get_indexes(table)} if name == INDEX])
        assert leftover == []

        # Downgrade then upgrade again is clean.
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        shape = await _shape(engine)
        assert TABLE in shape["tables"]
        assert INDEX in shape["indexes"]
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0053_completes_a_partially_applied_upgrade(tmp_path, backend):
    """The table already exists (an interrupted earlier attempt): upgrade still lands."""
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            # The table exists but its index was never built (an interrupted earlier attempt).
            await conn.run_sync(Base.metadata.create_all, tables=[ExternalLoginTicketRow.__table__])
            await conn.execute(sa.text(f"DROP INDEX {INDEX}"))
            await conn.execute(sa.insert(ExternalLoginTicketRow).values(jti="jti-2", user_id="user-2", consumed_at=sa.func.now(), expires_at=sa.func.now()))

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert INDEX in (await _shape(engine))["indexes"]  # the partial upgrade is completed
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text(f"SELECT user_id FROM {TABLE} WHERE jti='jti-2'"))).scalar_one() == "user-2"
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == REVISION

        # A downgrade after someone already dropped the table still completes.
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE {TABLE}"))
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == PREVIOUS
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def test_bootstrap_provisions_the_table_on_an_empty_database_and_is_idempotent(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}")
    try:
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        shape = await _shape(engine)
        assert set(shape["columns"]) == COLUMNS
        assert INDEX in shape["indexes"]
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == bootstrap._get_head_revision()
    finally:
        await engine.dispose()
