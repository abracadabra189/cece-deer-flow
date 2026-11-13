"""Regression anchors: the public auth routes must read the live config off the loop.

``get_app_config()`` stats and re-hashes ``config.yaml`` and
``extensions_config.json`` on every call, and reparses them after an edit.
``/register``, ``/setup-status``, ``/providers``, ``/oauth/{provider}``,
``/callback/{provider}`` and the two ``/external/`` routes are unauthenticated
and each read the live ``auth`` section, so the read runs in a worker, as
``/login/local``'s throttle policy does (``test_login_local_throttle.py``).

Each request runs against real config files and asserts an answer only the
file on disk produces (registration closed, the configured SSO provider, the
configured external-user key and frontend base URL), so an anchor cannot pass
because the route stopped reading the config.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from blockbuster import BlockingError
from fastapi import FastAPI

from app.gateway.auth import config as auth_config_module
from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.routers import auth as auth_router
from app.gateway.routers import external_users as external_users_router
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config

pytestmark = pytest.mark.asyncio

_CONFIG_YAML = """sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
auth:
  local:
    allow_registration: false
  oidc:
    enabled: true
    frontend_base_url: https://deerflow.example.com
    providers:
      corp:
        display_name: Corp SSO
        issuer: https://sso.example.com
        client_id: deerflow
  external_user:
    enabled: true
    api_key: external-anchor-key-0123456789
    frontend_base_url: https://deerflow.example.com
"""


def _write_configs(directory: Path) -> tuple[Path, Path]:
    config_path = directory / "config.yaml"
    extensions_path = directory / "extensions_config.json"
    config_path.write_text(_CONFIG_YAML, encoding="utf-8")
    extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    return config_path, extensions_path


@pytest.fixture
def local_provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    provider = AsyncMock()
    provider.count_admin_users.return_value = 0
    monkeypatch.setattr(auth_router, "get_local_provider", lambda: provider)
    monkeypatch.setattr(external_users_router, "get_local_provider", lambda: provider)
    return provider


@pytest.fixture
def pinned_jwt_secret() -> Iterator[str]:
    """Pin the signing secret so ticket verification does no lazy file I/O."""
    previous = auth_config_module._auth_config
    set_auth_config(AuthConfig(jwt_secret="blocking-io-anchor-secret-0123456789"))
    try:
        yield "blocking-io-anchor-secret-0123456789"
    finally:
        auth_config_module._auth_config = previous


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local_provider: AsyncMock) -> AsyncIterator[httpx.AsyncClient]:
    config_path, extensions_path = await asyncio.to_thread(_write_configs, tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    monkeypatch.setattr(auth_router, "_SETUP_STATUS_CACHE", {})
    monkeypatch.setattr(auth_router, "_SETUP_STATUS_INFLIGHT", {})
    reset_app_config()
    reset_extensions_config()
    # Load once off the loop: each request then only pays the per-call
    # revalidation, which is the cost every unauthenticated request carries.
    await asyncio.to_thread(get_app_config)

    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(external_users_router.router)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as http_client:
            yield http_client
    finally:
        reset_app_config()
        reset_extensions_config()


async def test_register_reads_registration_gate_off_the_loop(client: httpx.AsyncClient, local_provider: AsyncMock) -> None:
    response = await client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "Str0ng!Passw0rd#2026"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "registration_disabled"
    local_provider.create_user.assert_not_called()


async def test_setup_status_reads_registration_gate_off_the_loop(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/setup-status")

    assert response.status_code == 200
    assert response.json() == {"needs_setup": True, "registration_enabled": False}


async def test_providers_reads_oidc_config_off_the_loop(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/providers")

    assert response.status_code == 200
    assert response.json() == {"providers": [{"id": "corp", "display_name": "Corp SSO", "type": "oidc"}]}


async def test_oauth_login_reads_oidc_config_off_the_loop(client: httpx.AsyncClient) -> None:
    # An unconfigured provider is rejected right after the config read, before
    # any discovery request to the IdP.
    response = await client.get("/api/v1/auth/oauth/other")

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown SSO provider: other"


async def test_oauth_callback_reads_oidc_config_off_the_loop(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/callback/corp", params={"error": "access_denied"})

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://deerflow.example.com/")


async def test_external_provision_reads_config_off_the_loop(client: httpx.AsyncClient, local_provider: AsyncMock) -> None:
    """Both the enabled flag and the key come from the file: a wrong key is 401, not 404."""
    response = await client.post(
        "/api/v1/auth/external/provision",
        json={"account": "anchor-account", "phone": "+8613800138000"},
        headers={"X-External-User-Key": "not-the-configured-key"},
    )

    assert response.status_code == 401
    local_provider.get_user_by_oauth.assert_not_called()


async def test_external_login_reads_config_off_the_loop(client: httpx.AsyncClient, pinned_jwt_secret: str) -> None:
    response = await client.get("/api/v1/auth/external/login", params={"ticket": "not-a-ticket"})

    assert response.status_code == 302
    # The failure redirect carries the frontend base URL from the config file.
    assert response.headers["location"] == "https://deerflow.example.com/login?error=external_login_failed"


@pytest.mark.parametrize("read", [auth_router._local_registration_enabled, get_app_config], ids=["registration", "app-config"])
async def test_blocking_probe_inline_config_read_actually_trips_the_gate(client: httpx.AsyncClient, read) -> None:
    """Meta-check: the same reads inline on the loop are caught by the gate."""
    with pytest.raises(BlockingError):
        read()
