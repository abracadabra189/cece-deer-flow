"""Read-only data access for the operations console.

Two independent engines:
- PostgreSQL: the DeerFlow application tables, one pooled connection.
- MySQL: optional, only to map a user's ``code`` / ``name`` / ``mobile``.

Nothing here writes. The PostgreSQL role is expected to be read-only and
``default_transaction_read_only`` is set on it.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("OPS_DATABASE_URL", "")
DB_SCHEMA = os.environ.get("OPS_DB_SCHEMA", "").strip()
STATEMENT_TIMEOUT_MS = max(1000, int(os.environ.get("OPS_STATEMENT_TIMEOUT_MS", "5000")))
PAGE_LIMIT = max(1, int(os.environ.get("OPS_PAGE_LIMIT", "200")))

MYSQL_HOST = os.environ.get("OPS_MYSQL_HOST", "").strip()
MYSQL_PORT = int(os.environ.get("OPS_MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("OPS_MYSQL_USER", "").strip()
MYSQL_PASSWORD = os.environ.get("OPS_MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("OPS_MYSQL_DB", "").strip()
MYSQL_TABLE = os.environ.get("OPS_MYSQL_TABLE", "st_mgr_user").strip()
MYSQL_CODE_COLUMN = os.environ.get("OPS_MYSQL_CODE_COLUMN", "code").strip()
MYSQL_MOBILE_COLUMN = os.environ.get("OPS_MYSQL_MOBILE_COLUMN", "mobile").strip()
MYSQL_NAME_COLUMN = os.environ.get("OPS_MYSQL_NAME_COLUMN", "name").strip()
CODE_CACHE_SECONDS = max(5, int(os.environ.get("OPS_CODE_CACHE_SECONDS", "300")))
MAP_EMAIL_DOMAIN = os.environ.get("OPS_MAP_EMAIL_DOMAIN", "users.deerflow.internal").strip().lower()

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_mysql_engine: AsyncEngine | None = None
_code_cache: tuple[float, tuple[str, ...], tuple[dict[str, str], dict[str, tuple[str, str]]]] | None = None

_CACHE: dict[Any, tuple[float, Any]] = {}


def _engine_or_raise() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError("OPS_DATABASE_URL is not set")
        server_settings: dict[str, str] = {
            "application_name": "deerflow-ops",
            "statement_timeout": str(STATEMENT_TIMEOUT_MS),
        }
        if DB_SCHEMA:
            server_settings["search_path"] = DB_SCHEMA
        _engine = create_async_engine(
            DATABASE_URL,
            # One connection is enough for a single operator and keeps the
            # production connection budget untouched.
            pool_size=1,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={"server_settings": server_settings},
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def fetch(sql: str, **params: Any) -> list[dict[str, Any]]:
    engine = _engine_or_raise()
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return [dict(row._mapping) for row in result]


async def cached[T](key: Any, ttl: int, factory: Callable[[], Awaitable[T]]) -> T:
    """Small in-process TTL cache for aggregate queries.

    The console is a single process for one operator; a dict is enough. Callers
    pass a complete key (including every filter) so results never mix.
    """
    now = time.monotonic()
    item = _CACHE.get(key)
    if item is not None and now - item[0] < ttl:
        return item[1]
    value = await factory()
    _CACHE[key] = (now, value)
    return value


def _mysql_engine_or_none() -> AsyncEngine | None:
    global _mysql_engine
    if not (MYSQL_HOST and MYSQL_USER and MYSQL_DB):
        return None
    if _mysql_engine is None:
        url = URL.create(
            "mysql+aiomysql",
            username=MYSQL_USER,
            password=MYSQL_PASSWORD,
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            database=MYSQL_DB,
        )
        _mysql_engine = create_async_engine(
            url,
            pool_size=1,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
    return _mysql_engine


async def fetch_codes(prefixes: list[str]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Read only the MySQL rows that match this deployment's PG users."""
    engine = _mysql_engine_or_none()
    if engine is None:
        return {}, {}
    codes_csv = ",".join(sorted({prefix for prefix in prefixes if prefix}))
    mobiles_csv = ",".join(sorted({prefix for prefix in prefixes if prefix.isdigit()}))
    if not codes_csv and not mobiles_csv:
        return {}, {}
    table = MYSQL_TABLE if IDENT_RE.match(MYSQL_TABLE) else "st_mgr_user"
    column = MYSQL_CODE_COLUMN if IDENT_RE.match(MYSQL_CODE_COLUMN) else "code"
    mobile_column = MYSQL_MOBILE_COLUMN if IDENT_RE.match(MYSQL_MOBILE_COLUMN) else "mobile"
    name_column = MYSQL_NAME_COLUMN if IDENT_RE.match(MYSQL_NAME_COLUMN) else "name"
    # Identifiers are validated above; they cannot be bound as parameters.
    sql = f"""
        SELECT LOWER({column}) AS code, {mobile_column} AS mobile, {name_column} AS name
        FROM {table}
        WHERE FIND_IN_SET(LOWER({column}), :codes) > 0
           OR FIND_IN_SET({mobile_column}, :mobiles) > 0
    """
    code_names: dict[str, str] = {}
    by_mobile: dict[str, tuple[str, str]] = {}
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), {"codes": codes_csv, "mobiles": mobiles_csv})
        for row in result:
            code = str(row[0] or "")
            if not code:
                continue
            name = str(row[2] or "").strip()
            code_names[code] = name
            digits = re.sub(r"\D", "", str(row[1] or ""))
            if digits:
                by_mobile[digits] = (code, name)
    return code_names, by_mobile


async def codes_cached(prefixes: list[str]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    global _code_cache
    key = tuple(sorted({prefix for prefix in prefixes if prefix}))
    now = time.monotonic()
    if _code_cache is not None and now - _code_cache[0] < CODE_CACHE_SECONDS and _code_cache[1] == key:
        return _code_cache[2]
    try:
        maps = await fetch_codes(prefixes)
    except Exception:  # noqa: BLE001 - mapping is optional, never break the page
        maps = _code_cache[2] if _code_cache is not None and _code_cache[1] == key else ({}, {})
    _code_cache = (now, key, maps)
    return maps


async def user_code_map() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Map PG user IDs to MySQL code, email and name.

    Only emails on ``MAP_EMAIL_DOMAIN`` are eligible. Their prefix is matched
    against ``code`` first, then against the digits of ``mobile``. Users
    without a match keep their email.
    """
    rows = await fetch("SELECT id, email FROM users")
    domain_suffix = f"@{MAP_EMAIL_DOMAIN}" if MAP_EMAIL_DOMAIN else ""
    emails: dict[str, str] = {}
    prefixes: list[str] = []
    for row in rows:
        user_id = str(row["id"])
        email = str(row["email"] or "").strip()
        emails[user_id] = email
        if domain_suffix and email.lower().endswith(domain_suffix):
            prefixes.append(email.split("@", 1)[0].lower())

    code_names, by_mobile = await codes_cached(prefixes)
    by_id: dict[str, str] = {}
    names: dict[str, str] = {}
    for user_id, email in emails.items():
        if not domain_suffix or not email.lower().endswith(domain_suffix):
            continue
        prefix = email.split("@", 1)[0].lower()
        if prefix in code_names:
            by_id[user_id] = prefix
            names[user_id] = code_names[prefix]
        elif prefix.isdigit() and prefix in by_mobile:
            code, name = by_mobile[prefix]
            by_id[user_id] = code
            names[user_id] = name
    return by_id, emails, names


def resolve_user_ids(who: str, codes_by_id: dict[str, str], emails_by_id: dict[str, str], names_by_id: dict[str, str]) -> str:
    """Resolve a name/code/email fragment to a comma-separated user ID list."""
    needle = who.strip().lower()
    if not needle:
        return ""
    matches: list[str] = []
    for user_id, email in emails_by_id.items():
        code = codes_by_id.get(user_id, "")
        name = names_by_id.get(user_id, "")
        if needle in email.lower() or (code and needle in code) or (name and needle in name.lower()):
            matches.append(user_id)
    return ",".join(matches)
