"""Local password-login gate (``auth.local.password_login_enabled``).

A deployment whose accounts are provisioned by an external user system (or by SSO)
has no reason to keep ``POST /api/v1/auth/login/local`` open: externally provisioned
rows carry ``password_hash IS NULL`` so they cannot authenticate there anyway, while
every legacy local account remains a way in that bypasses the external system's
offboarding. ``allow_registration`` only closes sign-up, so this is the switch that
closes sign-in.

The gate must not be a session revocation: flipping it off has to leave already-issued
cookies working, or turning it on in production would log everybody out at once.
"""

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.routers import auth as auth_router
from deerflow.config.auth_config import AuthAppConfig, LocalAuthConfig

_TEST_SECRET = "test-secret-key-for-password-login-gate-tests-only"


@pytest.fixture(autouse=True)
def _persistence_engine(tmp_path):
    """Per-test SQLite engine + clean ``deps._cached_*`` (mirrors test_local_registration_gate)."""
    import asyncio

    from app.gateway import deps
    from deerflow.persistence.engine import close_engine, init_engine

    asyncio.run(init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path}/password_login_gate.db", sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        asyncio.run(close_engine())


@pytest.fixture
def gate(monkeypatch):
    """One live app whose ``auth.local`` section the test can flip between requests.

    A single client keeps the cookie jar, which is what lets the session-survival
    case disable password login *after* signing in. The gate is read per request, so
    swapping the patched config is enough — no second app, no re-login.
    """
    from pathlib import Path

    from deerflow.config.app_config import AppConfig

    # config.yaml is gitignored; the committed example gives every other section
    # (database above all) a real value for the app lifespan.
    baseline = AppConfig.from_file(str(Path(__file__).resolve().parents[2] / "config.example.yaml"))
    holder: dict[str, LocalAuthConfig] = {"local": LocalAuthConfig()}

    def _config() -> AppConfig:
        patched = baseline.model_copy(deep=True)
        patched.auth = AuthAppConfig(local=holder["local"], oidc=baseline.auth.oidc)
        return patched

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", _config)
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))

    from app.gateway.app import create_app

    client = TestClient(create_app())

    def _set(**overrides) -> None:
        holder["local"] = LocalAuthConfig(**overrides)
        # setup-status memoizes per client IP; drop it so each direction reads fresh.
        auth_router._SETUP_STATUS_CACHE.clear()

    return client, _set


def _register(client: TestClient, email: str, password: str = "Tr0ub4dor3a!"):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def _login(client: TestClient, email: str, password: str = "Tr0ub4dor3a!"):
    return client.post("/api/v1/auth/login/local", data={"username": email, "password": password})


def test_login_works_by_default(gate):
    """The default must stay enabled — this is an opt-in switch, not a flipped default."""
    client, _ = gate
    email = "gate-default@test.com"
    assert _register(client, email).status_code == 201

    assert _login(client, email).status_code == 200


def test_login_rejected_when_password_login_disabled(gate):
    client, set_gate = gate
    email = "gate-disabled@test.com"
    assert _register(client, email).status_code == 201

    set_gate(password_login_enabled=False)
    resp = _login(client, email)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "password_login_disabled"


def test_the_gate_runs_before_credentials_are_checked(gate):
    """A disabled deployment answers 403 for *wrong* credentials too.

    Pinning this keeps the gate ahead of ``authenticate``: placed after it, the
    endpoint would keep answering 401/200 by password and become a credential
    oracle for accounts the operator meant to close.
    """
    client, set_gate = gate
    email = "gate-no-oracle@test.com"
    assert _register(client, email).status_code == 201

    set_gate(password_login_enabled=False)

    assert _login(client, email, password="definitely-wrong").status_code == 403


def test_a_denied_login_does_not_consume_the_throttle_budget(gate):
    """Denied-by-policy attempts must not lock the client IP out of a later real login.

    The gate sits before the rate limiter on purpose: a closed endpoint that still
    counted failures would lock a shared egress IP (corporate NAT) for
    ``lockout_seconds`` the moment the operator reopened it.
    """
    client, set_gate = gate
    email = "gate-throttle@test.com"
    assert _register(client, email).status_code == 201

    set_gate(password_login_enabled=False)
    for _ in range(8):  # above the default max_login_attempts=5
        assert _login(client, email).status_code == 403

    set_gate(password_login_enabled=True)

    assert _login(client, email).status_code == 200


def test_an_existing_session_survives_closing_password_login(gate):
    """Flipping the switch off is not a mass logout.

    Operators enable this on a running deployment; if it invalidated live cookies,
    every signed-in user — including the admin doing the change — would be dropped
    at once, and on an external-only deployment the login page is a dead end.
    """
    client, set_gate = gate
    email = "gate-session-survives@test.com"
    assert _register(client, email).status_code == 201
    assert _login(client, email).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200

    set_gate(password_login_enabled=False)

    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("enabled", [True, False])
def test_setup_status_reports_the_password_login_state(gate, enabled):
    """The login page reads this to decide whether to render the password form."""
    client, set_gate = gate

    set_gate(password_login_enabled=enabled)
    resp = client.get("/api/v1/auth/setup-status")

    assert resp.status_code == 200
    assert resp.json()["password_login_enabled"] is enabled


def test_password_login_defaults_to_enabled():
    assert LocalAuthConfig().password_login_enabled is True
    assert AuthAppConfig().local.password_login_enabled is True


def test_gate_falls_back_to_enabled_when_config_is_absent(monkeypatch):
    """No config.yaml → the pre-gate behavior (enabled), not a 500.

    Mirrors ``_local_registration_enabled``: only FileNotFoundError is caught, so a
    malformed config propagates instead of silently reopening a closed deployment.
    """

    def _raise() -> None:
        raise FileNotFoundError("`config.yaml` file not found in the project root")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", _raise)

    assert auth_router._local_password_login_enabled() is True


def test_registration_and_initialize_keep_their_own_gate(gate):
    """Closing password login must not close first-boot admin creation or sign-up.

    ``allow_registration`` stays the owner of ``/register``; ``/initialize`` remains
    ungated so a fresh install can still create its first admin.
    """
    client, set_gate = gate

    set_gate(password_login_enabled=False)

    assert _register(client, "gate-register-still-open@test.com").status_code == 201
    assert client.post("/api/v1/auth/initialize", json={"email": "gate-initialize@test.com", "password": "Tr0ub4dor3a!"}).status_code in (201, 400)
