"""External-user configuration and legacy migration compatibility."""

import asyncio

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.config.auth_config import AuthAppConfig
from deerflow.persistence import bootstrap


def test_external_user_config_is_preserved_and_validated() -> None:
    config = AuthAppConfig.model_validate(
        {
            "external_user": {
                "enabled": True,
                "api_key": "x" * 16,
            }
        }
    )

    assert config.external_user.enabled is True
    assert config.external_user.api_key == "x" * 16


def test_external_user_router_keeps_both_trusted_entrypoints() -> None:
    """Restoring config alone must not leave the integration unreachable."""
    from app.gateway.routers.external_users import router

    paths = {route.path for route in router.routes}
    assert "/api/v1/auth/external/provision" in paths
    assert "/api/v1/auth/external/login" in paths


@pytest.mark.asyncio
async def test_bootstrap_upgrades_legacy_external_login_ticket_revision(tmp_path) -> None:
    """A deployed external-user database must rejoin the current migration head."""
    assert len(bootstrap._get_head_revision()) <= 32

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    config = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, config, "0052_batch_continuation")
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE external_login_tickets (jti VARCHAR(64) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, consumed_at DATETIME NOT NULL, expires_at DATETIME NOT NULL)"))
            await connection.execute(text("CREATE INDEX ix_external_login_tickets_expires_at ON external_login_tickets (expires_at)"))
        await asyncio.to_thread(
            command.stamp,
            config,
            "0053_external_login_tickets",
            purge=True,
        )

        await bootstrap.bootstrap_schema(engine, backend="sqlite")

        async with engine.connect() as connection:
            revisions = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            assert revisions == [bootstrap._get_head_revision()]
            assert (await connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'external_login_tickets'"))).scalar_one() == "external_login_tickets"
            assert (await connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tool_approvals'"))).scalar_one() == "tool_approvals"
    finally:
        await engine.dispose()
