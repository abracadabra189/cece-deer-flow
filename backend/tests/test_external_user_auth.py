"""External user-system integration: phone provisioning, one-time login tickets, session cookies.

The point of these tests is the trust boundary, not just the happy path: the
provisioning key is worth an account for any phone number, so every test that can
fail closed (disabled feature, missing key, wrong key, replayed ticket, tampered
ticket, disabled account, colliding email) is pinned alongside the flow that works.

Both tiers run against a real SQLite ``users`` table. The engine is loop-bound, so
the provisioning tier is async (one loop per test) and the HTTP tier initializes
the engine inside the TestClient's own lifespan loop.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from uuid import uuid4

import jwt as pyjwt
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.gateway.auth import config as auth_config_module
from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.errors import TokenError
from app.gateway.auth.external_provisioning import (
    canonical_account,
    derive_email,
    get_or_provision_external_user,
    normalize_account,
    normalize_phone,
    normalize_username,
    resolve_role,
)
from app.gateway.auth.external_ticket import (
    TICKET_PURPOSE,
    create_external_login_ticket,
    verify_external_login_ticket,
)
from app.gateway.auth.jwt import create_access_token, decode_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME
from app.gateway.routers import external_users
from deerflow.config.auth_config import ExternalUserAuthConfig

_API_KEY = "external-provisioning-test-key-0123456789"
_JWT_SECRET = "external-user-auth-test-secret"
_PHONE = "+8613800138000"
_DOMAIN = "users.deerflow.internal"
#: The identity key: an external account name (ASCII here so the derived email stays readable).
_ACCOUNT = "zhang.san"
_IDENTITY = "zhang.san"
#: A CJK account canonicalizes to itself but hashes into the derived email.
_ACCOUNT_CJK = "张三"


def _config(**overrides) -> ExternalUserAuthConfig:
    values: dict = {"enabled": True, "api_key": _API_KEY, "email_domain": _DOMAIN}
    values.update(overrides)
    return ExternalUserAuthConfig(**values)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fixed_jwt_secret():
    """A deterministic signing secret for ticket/JWT assertions."""
    previous = auth_config_module._auth_config
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))
    yield _JWT_SECRET
    auth_config_module._auth_config = previous


@pytest_asyncio.fixture
async def db(tmp_path):
    """A real SQLite users table plus the provider over it (one loop per test)."""
    from types import SimpleNamespace

    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path}/external.db", sqlite_dir=str(tmp_path))
    repository = SQLiteUserRepository(get_session_factory())
    try:
        yield SimpleNamespace(repo=repository, provider=LocalAuthProvider(repository=repository))
    finally:
        await close_engine()


@pytest.fixture
def provider(db):
    return db.provider


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient whose app owns the engine, so requests and the DB share one loop.

    The two ``__test`` routes exist because a test cannot touch the engine from
    its own loop: reading a preference or disabling an account has to happen
    inside the request loop, so the assertions go through the app.
    """
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    holder: dict[str, object] = {}

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path}/http.db", sqlite_dir=str(tmp_path))
        holder["repo"] = SQLiteUserRepository(get_session_factory())
        holder["provider"] = LocalAuthProvider(repository=holder["repo"])
        try:
            yield
        finally:
            await close_engine()

    app = FastAPI(lifespan=_lifespan)
    app.include_router(external_users.router)

    @app.get("/__test/preferences/{user_id}")
    async def _read_preferences(user_id: str) -> dict:
        from deerflow.persistence.user.preferences import UserPreferencesRepository

        return await UserPreferencesRepository(get_session_factory()).get(user_id)

    @app.post("/__test/disable/{user_id}")
    async def _disable_user(user_id: str) -> dict:
        await holder["repo"].set_disabled(user_id, True)
        return {"disabled": True}

    monkeypatch.setattr(external_users, "get_local_provider", lambda: holder["provider"])

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def enabled(monkeypatch):
    def _enable(**overrides) -> ExternalUserAuthConfig:
        config = _config(**overrides)
        monkeypatch.setattr(external_users, "_live_config", lambda: config)
        return config

    return _enable


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.setattr(external_users, "_live_config", lambda: ExternalUserAuthConfig())


def _provision(
    client: TestClient,
    *,
    key: str | None = _API_KEY,
    account: str | None = _ACCOUNT,
    phone: str | None = _PHONE,
    username: str | None = "张三",
    **extra,
):
    """POST /provision. ``account``/``phone``/``username`` are omitted when None."""
    headers = {} if key is None else {"X-External-User-Key": key}
    body: dict = dict(extra)
    if account is not None:
        body["account"] = account
    if phone is not None:
        body["phone"] = phone
    if username is not None:
        body["username"] = username
    return client.post("/api/v1/auth/external/provision", json=body, headers=headers)


# ── config ───────────────────────────────────────────────────────────────────


class TestConfig:
    def test_disabled_by_default(self):
        config = ExternalUserAuthConfig()
        assert config.enabled is False
        assert config.api_key is None

    def test_enabled_requires_an_api_key(self):
        """An enabled endpoint without a key would mint accounts for anyone."""
        with pytest.raises(ValidationError, match="api_key is required"):
            ExternalUserAuthConfig(enabled=True)

    def test_a_short_api_key_is_rejected(self):
        with pytest.raises(ValidationError, match="at least 16 characters"):
            ExternalUserAuthConfig(enabled=True, api_key="short")

    def test_disabled_tolerates_a_missing_key(self):
        assert ExternalUserAuthConfig(enabled=False).api_key is None

    def test_api_key_is_stripped(self):
        assert ExternalUserAuthConfig(enabled=True, api_key=f"  {_API_KEY}  ").api_key == _API_KEY

    @pytest.mark.parametrize("provider_id", ["External Phone", "external_phone", "-lead", "trail-", "a" * 33])
    def test_provider_id_must_be_hyphen_case_and_fit_the_column(self, provider_id):
        with pytest.raises(ValidationError):
            _config(provider_id=provider_id)

    def test_provider_id_is_normalized(self):
        assert _config(provider_id="Corp-Users").provider_id == "corp-users"

    @pytest.mark.parametrize("domain", ["local", "users..internal", "-bad.internal", "bad-.internal", "spa ced.internal", "a@b.com", ""])
    def test_email_domain_must_be_a_dotted_hostname(self, domain):
        with pytest.raises(ValidationError):
            _config(email_domain=domain)

    @pytest.mark.parametrize("ttl", [0, 9, 901, -1])
    def test_ticket_ttl_is_bounded(self, ttl):
        with pytest.raises(ValidationError):
            _config(ticket_ttl_seconds=ttl)

    def test_admin_phones_are_deduplicated_and_stripped(self):
        assert _config(admin_phones=[" 13800138000 ", "13800138000", "13900139000"]).admin_phones == ["13800138000", "13900139000"]

    def test_frontend_base_url_loses_its_trailing_slash(self):
        assert _config(frontend_base_url="https://deerflow.example/").frontend_base_url == "https://deerflow.example"


# ── input normalization ──────────────────────────────────────────────────────


class TestNormalization:
    """`account` is the identity; `phone` is optional contact data; `username` is a label."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("zhang.san", "zhang.san"),
            ("  Zhang.San  ", "Zhang.San"),  # display form keeps the caller's casing
            ("张三", "张三"),  # a CJK account name is valid
            ("13800138000", "13800138000"),
            ("zhang.san@corp.com", "zhang.san@corp.com"),
            ("１３８００１３８０００", "13800138000"),  # NFKC folds full-width digits
        ],
    )
    def test_account_display_form_is_nfkc_trimmed(self, raw, expected):
        assert normalize_account(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None, 42, ["zhang"]])
    def test_a_missing_account_is_rejected(self, raw):
        with pytest.raises(HTTPException) as exc:
            normalize_account(raw)
        assert exc.value.status_code == 422

    @pytest.mark.parametrize("raw", ["x" * 129, "bad\u202ename", "bad\x00name", "bad\x1bname"])
    def test_an_unsafe_account_is_rejected(self, raw):
        with pytest.raises(HTTPException) as exc:
            normalize_account(raw)
        assert exc.value.status_code == 422

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Zhang.San", "zhang.san"),  # casefolded: one person stays one account
            ("  zhang   san ", "zhang san"),  # interior whitespace runs collapse
            ("张三", "张三"),
            ("Zhang.San@Corp.com", "zhang.san@corp.com"),
        ],
    )
    def test_canonical_account_folds_case_and_whitespace(self, raw, expected):
        assert canonical_account(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("+86 138-0013-8000", "+8613800138000"),
            ("(+86) 138 0013 8000", "+8613800138000"),
            ("+8613800138000", "+8613800138000"),
            ("８６１３８００１３８０００", "8613800138000"),  # full-width, no plus stays plus-less
            ("１３８００１３８０００", "13800138000"),
        ],
    )
    def test_a_phone_shaped_account_canonicalizes_as_a_phone(self, raw, expected):
        """Identities issued while the phone number was the key stay resolvable."""
        assert canonical_account(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("13800138000", "13800138000"),
            ("+86 138-0013-8000", "+8613800138000"),
            ("(+86) 138 0013 8000", "+8613800138000"),
            ("１３８００１３８０００", "13800138000"),
        ],
    )
    def test_phone_separators_and_widths_normalize(self, raw, expected):
        assert normalize_phone(raw) == expected

    def test_phone_is_optional(self):
        assert normalize_phone(None) == ""
        assert normalize_phone("   ") == ""

    @pytest.mark.parametrize("raw", ["123", "123456789012345678901", "abc12345", "+", "1380013800a", 13800138000])
    def test_invalid_phones_are_rejected(self, raw):
        with pytest.raises(HTTPException) as exc:
            normalize_phone(raw)
        assert exc.value.status_code == 422

    def test_username_defaults_to_empty(self):
        assert normalize_username(None) == ""
        assert normalize_username("   ") == ""

    def test_username_is_stripped_and_bounded(self):
        assert normalize_username("  张三  ") == "张三"
        assert normalize_username("x" * 100) == "x" * 100

    @pytest.mark.parametrize("raw", ["x" * 101, "bad\u202ename", "bad\x00name", "bad\x1bname", 42])
    def test_unsafe_usernames_are_rejected(self, raw):
        with pytest.raises(HTTPException) as exc:
            normalize_username(raw)
        assert exc.value.status_code == 422

    def test_an_ascii_account_keeps_a_readable_local_part(self):
        assert derive_email("zhang.san", _DOMAIN) == f"zhang.san@{_DOMAIN}"

    def test_a_phone_identity_drops_the_plus(self):
        """Byte-identical to what phone-keyed provisioning derived, so old rows resolve."""
        assert derive_email("+8613800138000", _DOMAIN) == f"8613800138000@{_DOMAIN}"

    def test_a_cjk_account_hashes_into_the_local_part(self):
        address = derive_email("张三", _DOMAIN)
        local = address.split("@")[0]

        assert address.endswith(f"@{_DOMAIN}")
        assert local.startswith("u") and len(local) == 25 and local.isascii()
        assert derive_email("张三", _DOMAIN) == address  # deterministic

    def test_an_email_account_is_hashed_not_reused(self):
        """Reusing the caller's address would collide with a real mailbox's account."""
        address = derive_email("zhang.san@corp.com", _DOMAIN)

        assert address != "zhang.san@corp.com"
        assert address.endswith(f"@{_DOMAIN}")

    def test_distinct_accounts_never_share_an_address(self):
        assert derive_email("张三", _DOMAIN) != derive_email("李四", _DOMAIN)

    def test_an_overlong_ascii_account_falls_back_to_the_hash(self):
        assert derive_email("a" * 65, _DOMAIN).split("@")[0].startswith("u")

    def test_a_listed_account_or_phone_becomes_admin(self):
        config = _config(admin_phones=["+86 138-0013-8000", "Ops.Admin"], default_role="user")

        assert resolve_role(identity="+8613800138000", phone="", config=config) == "admin"
        assert resolve_role(identity="ops.admin", phone="", config=config) == "admin"
        assert resolve_role(identity="zhang.san", phone="+8613800138000", config=config) == "admin"
        assert resolve_role(identity="zhang.san", phone="", config=config) == "user"


# ── provisioning ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestProvisioning:
    async def test_first_sight_creates_the_account(self, provider):
        result = await get_or_provision_external_user(identity=_IDENTITY, config=_config(), local_provider=provider)

        assert result["created"] is True
        assert result["user"].email == derive_email(_IDENTITY, _DOMAIN)
        assert result["user"].oauth_provider == "external-phone"
        assert result["user"].oauth_id == _IDENTITY

    async def test_a_known_account_resolves_the_same_user(self, provider):
        config = _config()
        first = await get_or_provision_external_user(identity=_IDENTITY, config=config, local_provider=provider)
        second = await get_or_provision_external_user(identity=_IDENTITY, config=config, local_provider=provider)

        assert second["created"] is False
        assert str(second["user"].id) == str(first["user"].id)

    async def test_a_cjk_account_is_provisioned_and_resolvable(self, provider):
        config = _config()
        identity = canonical_account(_ACCOUNT_CJK)
        first = await get_or_provision_external_user(identity=identity, config=config, local_provider=provider)
        second = await get_or_provision_external_user(identity=identity, config=config, local_provider=provider)

        assert first["created"] is True
        assert first["user"].oauth_id == "张三"
        assert first["user"].email.startswith("u")  # hashed local part
        assert str(second["user"].id) == str(first["user"].id)

    async def test_an_email_account_does_not_collide_with_a_local_mailbox(self, provider):
        """The caller's address is hashed, so a real local account keeps its own email."""
        await provider.create_user(email="zhang.san@corp.com", password="v2$local-password", system_role="user")

        result = await get_or_provision_external_user(identity=canonical_account("zhang.san@corp.com"), config=_config(), local_provider=provider)

        assert result["created"] is True
        assert result["user"].email != "zhang.san@corp.com"
        assert result["user"].email.endswith(f"@{_DOMAIN}")

    async def test_a_legacy_phone_identity_is_still_resolved(self, provider):
        """An account issued when the phone number was the key keeps working."""
        config = _config()
        legacy = await provider.create_oauth_user(email=derive_email(_PHONE, _DOMAIN), oauth_provider="external-phone", oauth_id=_PHONE, system_role="user")

        result = await get_or_provision_external_user(identity=canonical_account("+86 138-0013-8000"), config=config, local_provider=provider)

        assert result["created"] is False
        assert str(result["user"].id) == str(legacy.id)

    async def test_created_accounts_have_no_password(self, provider):
        """Password login must stay impossible for an externally owned identity."""
        result = await get_or_provision_external_user(identity=_IDENTITY, config=_config(), local_provider=provider)

        assert result["user"].password_hash is None
        assert await provider.authenticate({"email": result["user"].email, "password": "anything"}) is None

    async def test_a_disabled_account_is_refused(self, db):
        created = (await get_or_provision_external_user(identity=_IDENTITY, config=_config(), local_provider=db.provider))["user"]
        await db.repo.set_disabled(str(created.id), True)

        with pytest.raises(HTTPException) as exc:
            await get_or_provision_external_user(identity=_IDENTITY, config=_config(), local_provider=db.provider)
        assert exc.value.status_code == 403

    async def test_an_unrelated_account_owning_the_derived_email_is_not_seized(self, provider):
        await provider.create_user(email=derive_email(_IDENTITY, _DOMAIN), password="v2$local-password", system_role="user")

        with pytest.raises(HTTPException) as exc:
            await get_or_provision_external_user(identity=_IDENTITY, config=_config(), local_provider=provider)
        assert exc.value.status_code == 409

    async def test_a_second_provider_id_may_not_share_the_derived_email(self, provider):
        """Two external systems need two ``email_domain`` values, or the second is refused."""
        await get_or_provision_external_user(identity=_IDENTITY, config=_config(provider_id="corp-a"), local_provider=provider)

        with pytest.raises(HTTPException) as exc:
            await get_or_provision_external_user(identity=_IDENTITY, config=_config(provider_id="corp-b"), local_provider=provider)
        assert exc.value.status_code == 409

    async def test_two_provider_ids_with_distinct_domains_coexist(self, provider):
        user_a = await get_or_provision_external_user(identity=_IDENTITY, config=_config(provider_id="corp-a", email_domain="a.deerflow.internal"), local_provider=provider)
        user_b = await get_or_provision_external_user(identity=_IDENTITY, config=_config(provider_id="corp-b", email_domain="b.deerflow.internal"), local_provider=provider)

        assert str(user_a["user"].id) != str(user_b["user"].id)

    async def test_a_listed_account_is_created_as_admin(self, provider):
        config = _config(admin_phones=["Zhang.San"])

        result = await get_or_provision_external_user(identity=_IDENTITY, config=config, local_provider=provider)

        assert result["user"].system_role == "admin"

    async def test_a_concurrent_create_resolves_the_winner(self, provider, monkeypatch):
        """The unique index turns the loser's insert into a re-read, not a 500."""
        real_create = provider.create_oauth_user
        calls = {"n": 0}

        async def _racing_create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                await real_create(**kwargs)  # the "other worker" wins the insert
                raise ValueError("UNIQUE constraint failed: users.email")
            return await real_create(**kwargs)

        monkeypatch.setattr(provider, "create_oauth_user", _racing_create)

        result = await get_or_provision_external_user(identity=_IDENTITY, config=_config(), local_provider=provider)

        assert result["created"] is False
        assert result["user"].oauth_id == _IDENTITY


# ── one-time tickets ─────────────────────────────────────────────────────────


class TestTicket:
    """Crypto half only — durable single-use consumption is covered by
    ``test_external_login_ticket_store.py`` and the route-level replay tests below.
    """

    def test_round_trip(self):
        ticket = create_external_login_ticket("user-1", ttl_seconds=60, next_path="/workspace/chats")
        payload = verify_external_login_ticket(ticket)

        assert payload is not None
        assert payload.uid == "user-1"
        assert payload.purpose == TICKET_PURPOSE
        assert payload.next_path == "/workspace/chats"
        assert payload.jti

    def test_a_forged_ticket_is_rejected(self):
        forged = pyjwt.encode(
            {"purpose": TICKET_PURPOSE, "uid": "admin", "jti": "x", "iat": time.time(), "exp": time.time() + 60},
            "wrong-secret",
            algorithm="HS256",
        )

        assert verify_external_login_ticket(forged) is None

    def test_a_truncated_ticket_is_rejected(self):
        ticket = create_external_login_ticket("user-1", ttl_seconds=60)

        assert verify_external_login_ticket(ticket[:-2] + "aa") is None

    def test_an_expired_ticket_is_rejected(self):
        payload = {"purpose": TICKET_PURPOSE, "uid": "user-1", "jti": "expired", "iat": time.time() - 600, "exp": time.time() - 300}

        assert verify_external_login_ticket(pyjwt.encode(payload, _JWT_SECRET, algorithm="HS256")) is None

    def test_a_wrong_purpose_or_missing_claim_is_rejected(self):
        base = {"purpose": "something_else", "uid": "user-1", "jti": "j", "iat": time.time(), "exp": time.time() + 60}
        assert verify_external_login_ticket(pyjwt.encode(base, _JWT_SECRET, algorithm="HS256")) is None
        for dropped in ("uid", "jti"):
            claims = {key: value for key, value in base.items() if key != dropped}
            claims["purpose"] = TICKET_PURPOSE
            assert verify_external_login_ticket(pyjwt.encode(claims, _JWT_SECRET, algorithm="HS256")) is None

    def test_a_session_jwt_is_not_a_ticket_and_a_ticket_is_not_a_session_jwt(self):
        """The claim shapes stay incompatible in both directions."""
        ticket = create_external_login_ticket("user-1", ttl_seconds=60)
        session = create_access_token("user-1")

        assert decode_token(ticket) == TokenError.MALFORMED
        assert verify_external_login_ticket(session) is None

    @pytest.mark.parametrize("token", ["", "   ", "not-a-jwt", None, 42])
    def test_garbage_is_rejected(self, token):
        assert verify_external_login_ticket(token) is None


# ── HTTP surface ─────────────────────────────────────────────────────────────


class TestProvisionRoute:
    def test_a_disabled_feature_is_not_discoverable(self, client, disabled):
        assert _provision(client).status_code == 404

    def test_a_missing_key_is_refused(self, client, enabled):
        enabled()

        assert _provision(client, key=None).status_code == 401

    def test_a_wrong_key_is_refused(self, client, enabled):
        enabled()

        assert _provision(client, key="not-the-key-not-the-key").status_code == 401

    def test_the_key_may_travel_as_a_bearer(self, client, enabled):
        enabled()
        response = client.post(
            "/api/v1/auth/external/provision",
            json={"account": _ACCOUNT},
            headers={"Authorization": f"Bearer {_API_KEY}"},
        )

        assert response.status_code == 200

    def test_a_new_account_is_registered_and_returned_with_credentials(self, client, enabled):
        enabled()
        response = _provision(client)

        assert response.status_code == 200
        body = response.json()
        assert body["created"] is True
        assert body["phone"] == _PHONE
        assert body["username"] == "张三"
        assert body["email"] == derive_email(_IDENTITY, _DOMAIN)
        assert body["system_role"] == "user"
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] > 0
        assert "ticket=" in body["login_url"]
        assert body["login_url"] == body["base_url"] + body["url_path"]
        # The returned JWT is a genuine session credential for that user.
        assert decode_token(body["access_token"]).sub == body["user_id"]

    def test_account_is_required(self, client, enabled):
        enabled()

        assert _provision(client, account=None).status_code == 422

    def test_an_empty_account_is_rejected(self, client, enabled):
        enabled()

        assert _provision(client, account="   ").status_code == 422

    def test_phone_is_optional(self, client, enabled):
        """The response shape is unchanged; `phone` simply reports null."""
        enabled()
        body = _provision(client, account="no-phone-account", phone=None).json()

        assert body["created"] is True
        assert body["phone"] is None
        assert body["email"] == derive_email("no-phone-account", _DOMAIN)
        assert decode_token(body["access_token"]).sub == body["user_id"]

    def test_username_falls_back_to_the_account(self, client, enabled):
        enabled()
        body = _provision(client, account="张三", username=None, phone=None).json()

        assert body["username"] == "张三"

    @pytest.mark.parametrize(
        ("account", "expected_local_part_prefix"),
        [
            ("张三", "u"),  # CJK → hashed local part
            ("13800138000", "13800138000"),  # numeric → readable
            ("zhang.san@corp.com", "u"),  # an email address → hashed, never reused
        ],
    )
    def test_account_may_be_cjk_numeric_or_an_email(self, client, enabled, account, expected_local_part_prefix):
        enabled()
        body = _provision(client, account=account, phone=None).json()

        assert body["created"] is True
        local_part = body["email"].split("@")[0]
        assert local_part.startswith(expected_local_part_prefix)
        assert body["email"].endswith(f"@{_DOMAIN}")
        # The same account resolves to the same user on a second call.
        assert _provision(client, account=account, phone=None).json()["user_id"] == body["user_id"]

    def test_an_account_and_a_phone_are_independent_identities(self, client, enabled):
        """One person under two account names is two DeerFlow users; phone is contact data."""
        enabled()
        first = _provision(client, account="acct-one", phone=_PHONE).json()
        second = _provision(client, account="acct-two", phone=_PHONE).json()

        assert first["user_id"] != second["user_id"]
        assert first["phone"] == second["phone"] == _PHONE

    def test_login_url_is_split_into_base_and_path(self, client, enabled):
        """Callers behind their own ingress re-base the path instead of editing a URL."""
        enabled()
        body = _provision(client, next="/workspace/chats").json()

        assert body["base_url"] == "http://testserver"
        assert body["url_path"].startswith("/api/v1/auth/external/login?ticket=")
        assert body["url_path"].endswith("&next=/workspace/chats")
        assert body["login_url"] == f"http://testserver{body['url_path']}"
        # The ticket in the path is the same one returned separately.
        assert body["login_ticket"] in body["url_path"]

    def test_a_configured_frontend_base_rebases_the_login_url(self, client, enabled):
        """The integrating backend may reach provision over an internal address.

        ``login_url`` is what a user's browser opens, so a configured public origin
        wins over the caller's ``Host``; otherwise every redirect lands somewhere
        only the caller can reach and the hand-off dies before the first page.
        """
        enabled(frontend_base_url="https://deerflow.example/")
        body = _provision(client).json()

        assert body["base_url"] == "https://deerflow.example"
        assert body["login_url"] == f"https://deerflow.example{body['url_path']}"

    def test_the_split_path_works_without_a_next_target(self, client, enabled):
        enabled()
        body = _provision(client, username=None).json()

        assert body["url_path"].startswith("/api/v1/auth/external/login?ticket=")
        assert "next=" not in body["url_path"]
        assert body["login_url"] == body["base_url"] + body["url_path"]

    def test_the_split_path_redeems_like_the_full_url(self, client, enabled):
        """Re-basing base_url must not change what the browser redeems."""
        enabled()
        body = _provision(client, next="/workspace/chats").json()

        response = client.get(body["url_path"], follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/auth/callback?next=/workspace/chats"
        assert ACCESS_TOKEN_COOKIE_NAME in response.cookies

    def test_an_existing_account_returns_the_same_user(self, client, enabled):
        enabled()
        first = _provision(client).json()
        second = _provision(client).json()

        assert second["created"] is False
        assert second["user_id"] == first["user_id"]
        # A fresh single-use ticket per call, so an earlier one cannot be replayed.
        assert second["login_ticket"] != first["login_ticket"]

    def test_an_invalid_phone_is_rejected(self, client, enabled):
        enabled()

        assert _provision(client, phone="12").status_code == 422

    def test_an_unsafe_username_is_rejected(self, client, enabled):
        enabled()

        assert _provision(client, username="bad\u202ename").status_code == 422

    def test_the_account_profile_is_stored_as_preferences(self, client, enabled):
        enabled()
        user_id = _provision(client, account="Zhang.San", username="李四").json()["user_id"]

        stored = client.get(f"/__test/preferences/{user_id}").json()

        assert stored[external_users.EXTERNAL_USERNAME_PREFERENCE_KEY] == "李四"
        # The account is stored in its display form, not the casefolded identity.
        assert stored[external_users.EXTERNAL_ACCOUNT_PREFERENCE_KEY] == "Zhang.San"
        assert stored[external_users.EXTERNAL_PHONE_PREFERENCE_KEY] == _PHONE

    def test_a_phoneless_provision_stores_no_phone_preference(self, client, enabled):
        enabled()
        user_id = _provision(client, account="no-phone-prefs", phone=None, username=None).json()["user_id"]

        stored = client.get(f"/__test/preferences/{user_id}").json()

        assert external_users.EXTERNAL_PHONE_PREFERENCE_KEY not in stored
        assert stored[external_users.EXTERNAL_ACCOUNT_PREFERENCE_KEY] == "no-phone-prefs"
        assert stored[external_users.EXTERNAL_USERNAME_PREFERENCE_KEY] == "no-phone-prefs"

    def test_an_admin_phone_is_provisioned_as_admin(self, client, enabled):
        enabled(admin_phones=[_PHONE])

        assert _provision(client).json()["system_role"] == "admin"

    def test_an_admin_account_is_provisioned_as_admin(self, client, enabled):
        enabled(admin_phones=["Ops.Admin"])

        assert _provision(client, account="ops.admin", phone=None).json()["system_role"] == "admin"


class TestLoginRoute:
    def _login(self, client: TestClient, ticket: str | None, *, next_param: str | None = None):
        params: dict[str, str] = {}
        if ticket is not None:
            params["ticket"] = ticket
        if next_param is not None:
            params["next"] = next_param
        return client.get("/api/v1/auth/external/login", params=params, follow_redirects=False)

    def test_a_valid_ticket_sets_the_session_cookies_and_lands_in_the_ui(self, client, enabled):
        enabled()
        provisioned = _provision(client).json()

        response = self._login(client, provisioned["login_ticket"])

        assert response.status_code == 302
        assert response.headers["location"].startswith("/auth/callback?next=/workspace")
        assert ACCESS_TOKEN_COOKIE_NAME in response.cookies
        assert CSRF_COOKIE_NAME in response.cookies
        assert decode_token(response.cookies[ACCESS_TOKEN_COOKIE_NAME]).sub == provisioned["user_id"]

    def test_the_requested_next_path_survives_the_redirect(self, client, enabled):
        enabled()
        provisioned = _provision(client, next="/workspace/chats").json()

        assert "next=/workspace/chats" in self._login(client, provisioned["login_ticket"]).headers["location"]

    def test_a_query_next_overrides_the_ticket_next(self, client, enabled):
        enabled()
        provisioned = _provision(client, next="/workspace/chats").json()

        assert "next=/projects" in self._login(client, provisioned["login_ticket"], next_param="/projects").headers["location"]

    def test_an_open_redirect_is_refused(self, client, enabled):
        enabled()
        provisioned = _provision(client, next="/workspace/chats").json()

        location = self._login(client, provisioned["login_ticket"], next_param="//evil.example").headers["location"]

        assert "evil.example" not in location
        assert "next=/workspace/chats" in location

    def test_a_ticket_cannot_be_redeemed_twice(self, client, enabled):
        enabled()
        provisioned = _provision(client).json()

        assert self._login(client, provisioned["login_ticket"]).status_code == 302
        replay = self._login(client, provisioned["login_ticket"])

        assert replay.headers["location"] == "/login?error=external_login_failed"
        assert ACCESS_TOKEN_COOKIE_NAME not in replay.cookies

    @pytest.mark.parametrize("ticket", ["garbage", ""])
    def test_an_unusable_ticket_fails_closed(self, client, enabled, ticket):
        enabled()
        response = self._login(client, ticket)

        assert response.status_code == 302
        assert response.headers["location"] == "/login?error=external_login_failed"
        assert ACCESS_TOKEN_COOKIE_NAME not in response.cookies

    def test_a_missing_ticket_fails_closed(self, client, enabled):
        enabled()

        assert self._login(client, None).headers["location"] == "/login?error=external_login_failed"

    def test_a_ticket_for_a_disabled_account_is_refused(self, client, enabled):
        enabled()
        provisioned = _provision(client).json()
        assert client.post(f"/__test/disable/{provisioned['user_id']}").status_code == 200

        response = self._login(client, provisioned["login_ticket"])

        assert response.headers["location"] == "/login?error=external_login_failed"
        assert ACCESS_TOKEN_COOKIE_NAME not in response.cookies

    def test_a_ticket_for_an_unknown_account_is_refused(self, client, enabled):
        enabled()

        assert self._login(client, create_external_login_ticket(str(uuid4()), ttl_seconds=60)).headers["location"] == "/login?error=external_login_failed"

    def test_login_is_closed_while_the_feature_is_disabled(self, client, disabled):
        response = self._login(client, create_external_login_ticket("user-1", ttl_seconds=60))

        assert response.headers["location"] == "/login?error=external_login_failed"
        assert ACCESS_TOKEN_COOKIE_NAME not in response.cookies

    def test_a_configured_frontend_base_is_used_for_the_redirect(self, client, enabled):
        enabled(frontend_base_url="https://deerflow.example")
        provisioned = _provision(client).json()

        assert self._login(client, provisioned["login_ticket"]).headers["location"].startswith("https://deerflow.example/auth/callback?next=")

    def test_the_browser_session_honors_the_configured_expiry(self, client, enabled):
        """``expires_in`` and the cookie the browser actually gets must agree.

        Provisioning promises ``session_expiry_minutes``; if the redeem step minted a
        default-lifetime token instead, the browser session would outlive what the
        integrating system was told — and a *shorter* promise than the real token
        means the user is 401'd while the caller still believes the session is live,
        which an external-only deployment cannot recover from on its own.
        """
        enabled(session_expiry_minutes=30)
        provisioned = _provision(client).json()
        assert provisioned["expires_in"] == 30 * 60

        token = self._login(client, provisioned["login_ticket"]).cookies[ACCESS_TOKEN_COOKIE_NAME]
        claims = pyjwt.decode(token, _JWT_SECRET, algorithms=["HS256"])

        assert claims["exp"] - claims["iat"] == 30 * 60
