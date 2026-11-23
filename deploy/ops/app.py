"""Read-only operations console for DeerFlow.

A standalone, deliberately small service:

- no authentication (bind it to loopback and use an SSH tunnel);
- only SELECT statements (point it at a read-only database role);
- no imports from ``deerflow`` or ``app`` (it must not drag the runtime in);
- every request carries a short statement timeout.

It reads the same tables the Gateway writes: ``users``, ``threads_meta``,
``runs`` and ``run_events``. Nothing is written back.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("OPS_DATABASE_URL", "")
DB_SCHEMA = os.environ.get("OPS_DB_SCHEMA", "").strip()
TZ = ZoneInfo(os.environ.get("OPS_TZ", "Asia/Shanghai"))
MAX_DAYS = max(1, int(os.environ.get("OPS_MAX_DAYS", "90")))
PAGE_LIMIT = max(1, int(os.environ.get("OPS_PAGE_LIMIT", "200")))
STATEMENT_TIMEOUT_MS = max(1000, int(os.environ.get("OPS_STATEMENT_TIMEOUT_MS", "5000")))

# Optional MySQL source for the user code. When unset or unreachable, the
# console falls back to the email prefix.
MYSQL_HOST = os.environ.get("OPS_MYSQL_HOST", "").strip()
MYSQL_PORT = int(os.environ.get("OPS_MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("OPS_MYSQL_USER", "").strip()
MYSQL_PASSWORD = os.environ.get("OPS_MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("OPS_MYSQL_DB", "").strip()
MYSQL_TABLE = os.environ.get("OPS_MYSQL_TABLE", "st_mgr_user").strip()
MYSQL_CODE_COLUMN = os.environ.get("OPS_MYSQL_CODE_COLUMN", "code").strip()
MYSQL_MOBILE_COLUMN = os.environ.get("OPS_MYSQL_MOBILE_COLUMN", "mobile").strip()
MYSQL_NAME_COLUMN = os.environ.get("OPS_MYSQL_NAME_COLUMN", "name").strip()
CODE_CACHE_SECONDS = max(5, int(os.environ.get("OPS_CODE_CACHE_SECONDS", "60")))
# Only emails on this domain are eligible for the code mapping. Personal
# accounts (qq.com, 163.com, ...) always display their email.
MAP_EMAIL_DOMAIN = os.environ.get("OPS_MAP_EMAIL_DOMAIN", "users.deerflow.internal").strip().lower()

THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

app = FastAPI(title="DeerFlow Ops", docs_url=None, redoc_url=None, openapi_url=None)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_mysql_engine: AsyncEngine | None = None
_code_cache: tuple[float, tuple[str, ...], tuple[dict[str, str], dict[str, tuple[str, str]]]] | None = None


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
            # One connection is enough for a single-operator page, and it keeps
            # the production connection budget untouched.
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


def _mysql_engine_or_none() -> AsyncEngine | None:
    """Return the optional MySQL engine; None means "no code mapping"."""
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
    """Read only the MySQL rows that match the PG users' email prefixes.

    A full ``st_mgr_user`` read is thousands of rows across the network; the
    console only needs the handful that belong to this deployment's users.
    """
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
    """Cache the maps briefly; a MySQL outage falls back to the last read."""
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
    """Map PG user IDs to their MySQL code and email.

    Only emails on ``MAP_EMAIL_DOMAIN`` are eligible. Their prefix is matched
    against MySQL ``code`` first, then against the digits of ``mobile``: an
    internal account may log in with either. The displayed label is always the
    lowercased code. Users without a match keep their email.
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
    """Resolve a name/code/email fragment to a comma-separated user ID list.

    Empty string means "no filter"; a non-empty string with no match means
    "match nothing", which the SQL expresses as an unmatched array.
    """
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


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def pretty_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


def clip(value: Any, limit: int = 160) -> str:
    text_value = "" if value is None else str(value)
    text_value = " ".join(text_value.split())
    if len(text_value) <= limit:
        return text_value
    return text_value[:limit] + "…"


def fmt_dt(value: Any) -> str:
    if not isinstance(value, datetime):
        return "—"
    return value.astimezone(TZ).strftime("%m-%d %H:%M")


def fmt_duration(start: Any, end: Any) -> str:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return "—"
    seconds = max(0, int((end - start).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def fmt_tokens(value: Any) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return "—"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(number)


def clamp_days(days: int) -> int:
    return max(1, min(MAX_DAYS, days))


def like(value: str) -> str:
    return f"%{value.strip()}%"


CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 20px 28px 60px;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", sans-serif;
  color: #1f2937; background: #f7f8fa;
}
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 20px; margin: 0 0 4px; }
.muted { color: #6b7280; font-size: 12px; }
.top { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 16px; min-width: 120px; }
.card .n { font-size: 20px; font-weight: 600; }
.card .k { color: #6b7280; font-size: 12px; }
form.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; background: #fff;
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px; margin-bottom: 16px; }
form.filters label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #6b7280; }
input, select, button { font: inherit; padding: 6px 9px; border: 1px solid #d1d5db; border-radius: 7px; background: #fff; }
button { cursor: pointer; background: #2563eb; color: #fff; border-color: #2563eb; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid #f0f1f3; vertical-align: top; }
th { background: #f9fafb; color: #4b5563; font-size: 12px; font-weight: 600; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: #fcfdff; }
.nowrap { white-space: nowrap; }
.q { color: #111827; }
.answer { color: #6b7280; font-size: 12px; margin-top: 2px; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 12px; white-space: nowrap; }
.ok { background: #dcfce7; color: #166534; }
.bad { background: #fee2e2; color: #991b1b; }
.run { background: #dbeafe; color: #1e40af; }
.other { background: #f3f4f6; color: #374151; }
.msg { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
.msg .who { font-size: 12px; color: #6b7280; margin-bottom: 6px; }
.msg .body { white-space: pre-wrap; word-break: break-word; }
.msg.human { border-left: 3px solid #2563eb; }
.msg.ai { border-left: 3px solid #10b981; }
.msg.tool { border-left: 3px solid #f59e0b; background: #fffdf5; }
.msg.error { border-left: 3px solid #ef4444; background: #fff5f5; }
.msg.trace { border-left: 3px solid #9ca3af; background: #fafafa; }
details summary { cursor: pointer; color: #4b5563; font-size: 12px; }
pre { white-space: pre-wrap; word-break: break-word; background: #f8fafc; padding: 8px; border-radius: 6px; font-size: 12px; }
.err { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; padding: 12px 14px; border-radius: 10px; margin-bottom: 16px; }
.back { margin-bottom: 14px; }
.trace { cursor: pointer; font-size: 11px; color: #2563eb; }
label.inline { flex-direction: row; align-items: center; gap: 6px; }
"""


def shell(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
{body}
<script>
document.addEventListener('click', async (event) => {{
  const target = event.target.closest('[data-copy]');
  if (!target) return;
  try {{
    await navigator.clipboard.writeText(target.dataset.copy);
    const previous = target.textContent;
    target.textContent = '已复制';
    setTimeout(() => {{ target.textContent = previous; }}, 1200);
  }} catch (error) {{
    target.textContent = target.dataset.copy;
  }}
}});
</script>
</body>
</html>""",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer",
        },
    )


def error_box(exc: Exception) -> str:
    return f'<div class="err"><b>查询失败</b><br>{esc(type(exc).__name__)}: {esc(exc)}</div>'


def status_badge(status: Any) -> str:
    value = str(status or "unknown")
    if value == "success":
        cls = "ok"
    elif value in {"error", "timeout", "interrupted"}:
        cls = "bad"
    elif value in {"pending", "running"}:
        cls = "run"
    else:
        cls = "other"
    label = {"success": "成功", "error": "失败", "timeout": "超时", "interrupted": "中断",
             "pending": "排队", "running": "运行中"}.get(value, value)
    return f'<span class="badge {cls}">{esc(label)}</span>'


def origin_label(value: Any) -> str:
    return {"schedule": "定时任务", "im_channel": "IM", "github": "GitHub",
            "extension": "扩展", "mcp_notification": "MCP"}.get(str(value or ""), "Web")


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> PlainTextResponse:
    if not DATABASE_URL:
        return PlainTextResponse("missing OPS_DATABASE_URL", status_code=503)
    try:
        await fetch("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001 - surfaced as a health failure
        return PlainTextResponse(f"unhealthy: {type(exc).__name__}", status_code=503)
    return PlainTextResponse("ok")


@app.get("/", response_class=HTMLResponse)
async def index(
    user: str = "",
    who: str = "",
    days: int = Query(7),
    status: str = "",
    origin: str = "",
    model: str = "",
    q: str = "",
    details: int = 0,
) -> HTMLResponse:
    days = clamp_days(days)
    where = [
        "r.operation_kind = 'run'",
        "r.created_at >= now() - make_interval(days => CAST(:days AS int))",
    ]
    params: dict[str, Any] = {"days": days, "limit": PAGE_LIMIT}
    if user:
        where.append("r.user_id = :user")
        params["user"] = user
    if status:
        where.append("r.status = :status")
        params["status"] = status
    if origin == "interactive":
        where.append("r.origin_kind IS NULL")
    elif origin:
        where.append("r.origin_kind = :origin")
        params["origin"] = origin
    if model.strip():
        where.append("r.model_name ILIKE :model")
        params["model"] = like(model)
    if q.strip():
        where.append("(r.first_human_message ILIKE :q OR r.last_ai_message ILIKE :q)")
        params["q"] = like(q)

    try:
        codes_by_id, emails_by_id, names_by_id = await user_code_map()
        who_ids = resolve_user_ids(who, codes_by_id, emails_by_id, names_by_id) if who.strip() else ""
        where_sql = " AND ".join(where)
        if who.strip():
            where_sql = f"({where_sql}) AND r.user_id = ANY(string_to_array(:who_ids, ','))"
            params["who_ids"] = who_ids

        stats = (
            await fetch(
                f"""
                SELECT count(*) AS runs,
                       count(*) FILTER (WHERE r.status IN ('error', 'timeout', 'interrupted')) AS failed,
                       coalesce(sum(r.total_tokens), 0) AS tokens,
                       count(DISTINCT r.user_id) AS users,
                       count(DISTINCT r.thread_id) AS threads
                FROM runs r
                WHERE {where_sql}
                """,
                **params,
            )
        )[0]
        rows = await fetch(
            f"""
            SELECT r.run_id, r.thread_id, r.user_id, r.status, r.model_name,
                   r.total_tokens, r.total_input_tokens, r.total_output_tokens,
                   r.llm_call_count, r.assistant_id,
                   r.created_at, r.updated_at, r.first_human_message,
                   r.last_ai_message, r.error, r.origin_kind,
                   r.metadata_json ->> 'deerflow_trace_id' AS trace_id,
                   t.display_name, u.email
            FROM runs r
            LEFT JOIN threads_meta t ON t.thread_id = r.thread_id
            LEFT JOIN users u ON u.id = r.user_id
            WHERE {where_sql}
            ORDER BY r.created_at DESC
            LIMIT :limit
            """,
            **params,
        )

        run_ids = [str(row["run_id"]) for row in rows]
        tools_by_run: dict[str, list[tuple[str, int]]] = {}
        errors_by_run: dict[str, str] = {}
        if run_ids:
            ids = ",".join(run_ids)
            # Tool results carry the tool name inside their JSON payload. This
            # aggregate scans run_events and parses JSON, so it is opt-in: the
            # default page must stay cheap even when the event table grows.
            if details:
                for tool_row in await fetch(
                    """
                    SELECT run_id, (content::jsonb) ->> 'name' AS tool, count(*) AS n
                    FROM run_events
                    WHERE run_id = ANY(string_to_array(:ids, ','))
                      AND event_type = 'llm.tool.result'
                      AND pg_input_is_valid(content, 'jsonb')
                    GROUP BY 1, 2
                    ORDER BY 1, n DESC
                    """,
                    ids=ids,
                ):
                    tool = str(tool_row["tool"] or "").strip()
                    if tool:
                        tools_by_run.setdefault(str(tool_row["run_id"]), []).append((tool, int(tool_row["n"])))
            for err_row in await fetch(
                """
                SELECT DISTINCT ON (run_id) run_id, event_metadata::jsonb ->> 'error_type' AS error_type
                FROM run_events
                WHERE run_id = ANY(string_to_array(:ids, ','))
                  AND event_type = 'run.error'
                ORDER BY run_id, seq
                """,
                ids=ids,
            ):
                if err_row["error_type"]:
                    errors_by_run[str(err_row["run_id"])] = str(err_row["error_type"])
    except Exception as exc:  # noqa: BLE001 - rendered in the page
        return shell("运营台", error_box(exc))

    cards = f"""
    <div class="cards">
      <div class="card"><div class="n">{int(stats['runs'] or 0)}</div><div class="k">runs（近 {days} 天）</div></div>
      <div class="card"><div class="n">{int(stats['failed'] or 0)}</div><div class="k">失败 / 超时</div></div>
      <div class="card"><div class="n">{fmt_tokens(stats['tokens'])}</div><div class="k">tokens</div></div>
      <div class="card"><div class="n">{int(stats['users'] or 0)}</div><div class="k">用户</div></div>
      <div class="card"><div class="n">{int(stats['threads'] or 0)}</div><div class="k">会话</div></div>
    </div>"""

    body_rows = []
    for row in rows:
        run_id = str(row["run_id"])
        question = clip(row["first_human_message"], 140) or "(无问题文本)"
        answer = clip(row["last_ai_message"], 90)
        error = clip(row["error"], 120)
        user_id = str(row["user_id"] or "")
        user_label = codes_by_id.get(user_id) or row["email"] or user_id or "—"
        user_email = emails_by_id.get(user_id) or row["email"] or ""
        user_name = names_by_id.get(user_id, "")
        user_note = " · ".join(part for part in (user_name, user_email) if part)
        tools = " ".join(f"{name}×{count}" for name, count in tools_by_run.get(run_id, [])[:4])
        tools_cell = esc(clip(tools, 36)) if details else '<span class="muted">未加载</span>'
        error_type = errors_by_run.get(run_id, "")
        trace_id = str(row["trace_id"] or "")
        duration = fmt_duration(row["created_at"], row["updated_at"])
        token_title = f"in {fmt_tokens(row['total_input_tokens'])} / out {fmt_tokens(row['total_output_tokens'])}"
        assistant = str(row["assistant_id"] or "")
        assistant_note = f'<div class="muted">{esc(assistant)}</div>' if assistant and assistant != "lead_agent" else ""
        run_cell = f'<a href="/runs/{esc(run_id)}" title="{esc(run_id)}">{esc(run_id[:8])}…</a>'
        trace_cell = (
            f'<code class="trace" data-copy="{esc(trace_id)}" title="{esc(trace_id)}">{esc(trace_id[:8])}…</code>'
            if trace_id
            else '<span class="muted">—</span>'
        )
        body_rows.append(
            f"""<tr>
  <td class="nowrap">{fmt_dt(row['created_at'])}<div class="muted">{esc(origin_label(row['origin_kind']))}</div></td>
  <td class="nowrap"><span title="{esc(user_note)}">{esc(user_label)}</span>
      {f'<div class="muted">{esc(user_name)}</div>' if user_name else ''}</td>
  <td><a href="/threads/{esc(row['thread_id'])}">{esc(clip(row['display_name'], 40) or '(未命名会话)')}</a>
      <div class="q">{esc(question)}</div>
      {f'<div class="answer">答：{esc(answer)}</div>' if answer else ''}
      {f'<div class="answer">错误：{esc(error)}</div>' if error else ''}
  </td>
  <td class="nowrap">{status_badge(row['status'])}
      {f'<div class="muted">{esc(error_type)}</div>' if error_type else ''}</td>
  <td class="nowrap">{duration}</td>
  <td class="nowrap" title="{esc(token_title)}">{fmt_tokens(row['total_tokens'])}</td>
  <td class="nowrap">{int(row['llm_call_count'] or 0)}</td>
  <td>{tools_cell or '—'}</td>
  <td class="nowrap">{esc(row['model_name'] or '—')}{assistant_note}</td>
  <td class="nowrap"><div class="muted">run</div>{run_cell}<div class="muted">trace</div>{trace_cell}</td>
</tr>"""
        )
    if not body_rows:
        body_rows.append('<tr><td colspan="10" class="muted">没有匹配的记录</td></tr>')

    who_notice = ""
    if who.strip() and not who_ids:
        who_notice = f'<div class="err">没有匹配「{esc(who)}」的用户（按名字 / 编码 / 邮箱匹配）</div>'

    origin_options = "".join(
        f'<option value="{value}" {"selected" if origin == value else ""}>{label}</option>'
        for value, label in [
            ("", "全部"),
            ("interactive", "Web"),
            ("schedule", "定时任务"),
            ("im_channel", "IM"),
            ("mcp_notification", "MCP"),
            ("extension", "扩展"),
            ("github", "GitHub"),
        ]
    )

    body = f"""
<div class="top">
  <div><h1>CeCeMate 运营台</h1><div class="muted">只读 · 数据截至 {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}</div></div>
  <div class="muted"><a href="/users">用户列表</a></div>
</div>
{cards}
{who_notice}
<form class="filters" method="get">
  <input type="hidden" name="user" value="{esc(user)}">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <label>名字 / 编码 / 邮箱<input name="who" value="{esc(who)}" placeholder="如 张三 / sh02311" style="width:200px"></label>
  <label>状态
    <select name="status">
      <option value="" {'selected' if not status else ''}>全部</option>
      <option value="success" {'selected' if status == 'success' else ''}>成功</option>
      <option value="error" {'selected' if status == 'error' else ''}>失败</option>
      <option value="running" {'selected' if status == 'running' else ''}>运行中</option>
    </select>
  </label>
  <label>来源<select name="origin">{origin_options}</select></label>
  <label>模型<input name="model" value="{esc(model)}" placeholder="可留空" style="width:150px"></label>
  <label>关键词<input name="q" value="{esc(q)}" placeholder="搜索问题 / 回答" style="width:180px"></label>
  <label class="inline"><input type="checkbox" name="details" value="1" {'checked' if details else ''}> 加载工具详情（较慢）</label>
  <button type="submit">筛选</button>
</form>
<div style="overflow-x:auto">
<table>
<thead><tr><th>时间</th><th>用户</th><th>会话 / 问题</th><th>状态</th><th>耗时</th><th>tokens</th><th>调用</th><th>工具</th><th>模型</th><th>run / trace</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
</div>
<div class="muted" style="margin-top:8px">最多显示 {PAGE_LIMIT} 条；缩小时间范围可看到更早的记录。点击 run 看这一轮的完整事件，点击 trace 可复制。工具详情默认不查询，勾选后才会扫事件表。</div>
"""
    return shell("运营台", body)


@app.get("/users", response_class=HTMLResponse)
async def users(days: int = Query(7), who: str = "") -> HTMLResponse:
    days = clamp_days(days)
    try:
        rows = await fetch(
            """
            SELECT u.id, u.email, u.system_role, u.disabled, u.created_at,
                   count(r.run_id) AS runs,
                   coalesce(sum(r.total_tokens), 0) AS tokens,
                   count(*) FILTER (WHERE r.status IN ('error', 'timeout', 'interrupted')) AS failed,
                   max(r.created_at) AS last_run
            FROM users u
            LEFT JOIN runs r
              ON r.user_id = u.id
             AND r.operation_kind = 'run'
             AND r.created_at >= now() - make_interval(days => CAST(:days AS int))
            GROUP BY u.id, u.email, u.system_role, u.disabled, u.created_at
            ORDER BY runs DESC, last_run DESC NULLS LAST
            LIMIT 500
            """,
            days=days,
        )
        codes_by_id, _, names_by_id = await user_code_map()
    except Exception as exc:  # noqa: BLE001
        return shell("用户", error_box(exc))

    if who.strip():
        needle = who.strip().lower()
        rows = [
            row for row in rows
            if needle in str(row["email"] or "").lower()
            or needle in codes_by_id.get(str(row["id"]), "")
            or needle in names_by_id.get(str(row["id"]), "").lower()
        ]

    body_rows = []
    for row in rows:
        user_id = str(row["id"])
        code = codes_by_id.get(user_id)
        email = str(row["email"] or "")
        name = names_by_id.get(user_id, "")
        # Show the mapped code when there is one, otherwise the PG email.
        label = code or email or user_id
        detail = " · ".join(part for part in (name, email) if part)
        secondary = f'<div class="muted">{esc(detail)}</div>' if code and detail else ""
        body_rows.append(
            f"""<tr>
  <td><a href="/?user={esc(user_id)}">{esc(label)}</a>{secondary}</td>
  <td class="nowrap">{esc(row['system_role'])}</td>
  <td class="nowrap">{'已禁用' if row['disabled'] else '正常'}</td>
  <td class="nowrap">{int(row['runs'] or 0)}</td>
  <td class="nowrap">{fmt_tokens(row['tokens'])}</td>
  <td class="nowrap">{int(row['failed'] or 0)}</td>
  <td class="nowrap">{fmt_dt(row['last_run'])}</td>
</tr>"""
        )
    if not body_rows:
        body_rows.append(f'<tr><td colspan="7" class="muted">{"没有匹配的用户" if who.strip() else "没有用户"}</td></tr>')

    body = f"""
<div class="back"><a href="/">← 返回运营台</a></div>
<div class="top"><h1>用户</h1><div class="muted">近 {days} 天 · 按活跃度排序</div></div>
<form class="filters" method="get">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <label>名字 / 编码 / 邮箱<input name="who" value="{esc(who)}" placeholder="如 张三 / sh02311" style="width:220px"></label>
  <button type="submit">筛选</button>
</form>
<table>
<thead><tr><th>用户</th><th>角色</th><th>状态</th><th>runs</th><th>tokens</th><th>失败</th><th>最近活跃</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
"""
    return shell("用户", body)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(run_id: str) -> HTMLResponse:
    if not RUN_ID_RE.match(run_id):
        return shell("Run", '<div class="err">非法的 run ID</div>')
    try:
        rows = await fetch(
            """
            SELECT r.*, t.display_name, u.email
            FROM runs r
            LEFT JOIN threads_meta t ON t.thread_id = r.thread_id
            LEFT JOIN users u ON u.id = r.user_id
            WHERE r.run_id = :rid
            """,
            rid=run_id,
        )
        if not rows:
            return shell("Run", f'<div class="err">找不到 run {esc(run_id)}</div>')
        run = rows[0]
        thread_id = str(run["thread_id"])
        events = await fetch(
            """
            SELECT seq, event_type, category, content, event_metadata, created_at
            FROM run_events
            WHERE thread_id = :tid AND run_id = :rid
            ORDER BY seq
            """,
            tid=thread_id,
            rid=run_id,
        )
        codes_by_id, emails_by_id, names_by_id = await user_code_map()
    except Exception as exc:  # noqa: BLE001
        return shell("Run", error_box(exc))

    user_id = str(run["user_id"] or "")
    user_label = codes_by_id.get(user_id) or run["email"] or user_id or "—"
    user_email = emails_by_id.get(user_id) or run["email"] or ""
    user_name = names_by_id.get(user_id, "")
    user_note = " · ".join(part for part in (user_name, user_email) if part)
    trace_id = str((run.get("metadata_json") or {}).get("deerflow_trace_id") or "")
    duration = fmt_duration(run["created_at"], run["updated_at"])
    assistant = str(run.get("assistant_id") or "")
    trace_cell = (
        f'<code class="trace" data-copy="{esc(trace_id)}" title="{esc(trace_id)}">{esc(trace_id)}</code>'
        if trace_id
        else '<span class="muted">—</span>'
    )
    run_cell = f'<code class="trace" data-copy="{esc(run_id)}" title="{esc(run_id)}">{esc(run_id)}</code>'

    cards = f"""
    <div class="cards">
      <div class="card"><div class="n">{duration}</div><div class="k">耗时</div></div>
      <div class="card"><div class="n">{fmt_tokens(run['total_tokens'])}</div><div class="k">tokens（{fmt_tokens(run['total_input_tokens'])} in / {fmt_tokens(run['total_output_tokens'])} out）</div></div>
      <div class="card"><div class="n">{int(run['llm_call_count'] or 0)}</div><div class="k">模型调用</div></div>
      <div class="card"><div class="n">{int(run['message_count'] or 0)}</div><div class="k">消息数</div></div>
      <div class="card"><div class="n">{esc(run['model_name'] or '—')}</div><div class="k">模型</div></div>
    </div>"""

    error_items: list[str] = []
    if run["error"]:
        error_items.append(
            f"""<div class="msg error">
  <div class="who">runs.error · stop_reason {esc(run['stop_reason'] or '—')}</div>
  <div class="body">{esc(clip(run['error'], 4000))}</div>
</div>"""
        )
    for event in events:
        if event["event_type"] not in ("run.error", "llm.error"):
            continue
        metadata = event["event_metadata"] or {}
        detail_lines = [
            f"{key}: {metadata.get(key)}"
            for key in ("error_type", "provider", "model", "caller", "request_chars", "request_message_count", "request_started_at")
            if metadata.get(key) is not None
        ]
        detail = "\n".join(detail_lines) or clip(event["content"], 2000)
        error_items.append(
            f"""<div class="msg error">
  <div class="who">{esc(event['event_type'])} · seq {int(event['seq'])} · {fmt_dt(event['created_at'])}</div>
  <div class="body">{esc(detail)}</div>
  <details><summary>原始 metadata</summary><pre>{esc(pretty_json(metadata))}</pre></details>
</div>"""
        )
    error_block = (
        '<div class="card" style="margin-bottom:12px"><div class="k">错误</div></div>' + "".join(error_items)
        if error_items
        else ""
    )

    rendered: list[str] = []
    for event in events:
        event_type = event["event_type"]
        if event_type in ("run.error", "llm.error"):
            continue
        if event_type == "llm.human.input":
            cls, who = "human", "用户"
        elif event_type == "llm.ai.response":
            cls, who = "ai", "助手"
        elif event_type == "llm.tool.result":
            cls, who = "tool", "工具结果"
        else:
            cls, who = "trace", event_type
        content = event["content"] or ""
        if cls in ("tool", "trace"):
            body_html = f"<details><summary>展开（{len(content)} 字符）</summary><pre>{esc(clip(content, 4000))}</pre></details>"
        else:
            body_html = f'<div class="body">{esc(clip(content, 4000))}</div>'
        rendered.append(
            f"""<div class="msg {cls}">
  <div class="who">{esc(who)} · seq {int(event['seq'])} · {fmt_dt(event['created_at'])}</div>
  {body_html}
</div>"""
        )
    if not rendered:
        rendered.append('<div class="muted">这一轮没有可显示的事件。</div>')

    title = f"Run {run_id[:12]}"
    body = f"""
<div class="back"><a href="/">← 返回运营台</a> · <a href="/threads/{esc(thread_id)}">完整会话</a></div>
<div class="top">
  <div><h1>{esc(title)}</h1>
    <div class="muted">用户 {esc(user_label)}（{esc(user_note)}） · 会话 {esc(thread_id)} · {fmt_dt(run['created_at'])}</div>
    <div class="muted">run {run_cell} · trace {trace_cell}</div>
    {f'<div class="muted">agent {esc(assistant)} · 来源 {esc(origin_label(run["origin_kind"]))}</div>' if assistant else ''}
  </div>
  <div>{status_badge(run['status'])}</div>
</div>
{cards}
{error_block}
<h2 style="font-size:15px;margin:18px 0 10px">事件时间线（{len(events)} 条）</h2>
{''.join(rendered)}
"""
    return shell(title, body)


@app.get("/threads/{thread_id}", response_class=HTMLResponse)
async def thread(thread_id: str) -> HTMLResponse:
    if not THREAD_ID_RE.match(thread_id):
        return shell("会话", '<div class="err">非法的会话 ID</div>')
    try:
        meta_rows = await fetch(
            """
            SELECT t.display_name, t.user_id, t.created_at, t.status, u.email
            FROM threads_meta t
            LEFT JOIN users u ON u.id = t.user_id
            WHERE t.thread_id = :tid
            """,
            tid=thread_id,
        )
        messages = await fetch(
            """
            SELECT seq, event_type, content, created_at
            FROM run_events
            WHERE thread_id = :tid
              AND category = 'message'
              AND event_type IN ('llm.human.input', 'llm.ai.response', 'llm.tool.result')
            ORDER BY seq
            LIMIT 1000
            """,
            tid=thread_id,
        )
        codes_by_id, emails_by_id, names_by_id = await user_code_map()
    except Exception as exc:  # noqa: BLE001
        return shell("会话", error_box(exc))

    meta = meta_rows[0] if meta_rows else None
    title = (meta["display_name"] if meta else None) or thread_id
    owner_id = str(meta["user_id"] or "") if meta else ""
    owner_code = codes_by_id.get(owner_id)
    owner_email = emails_by_id.get(owner_id) or (meta["email"] if meta else "") or ""
    owner_name = names_by_id.get(owner_id, "")
    owner_detail = " · ".join(part for part in (owner_name, owner_email) if part)
    owner_note = f"{owner_code}（{owner_detail}）" if owner_code and owner_detail else (owner_code or owner_detail or owner_id or "—")

    rendered = []
    for message in messages:
        event_type = message["event_type"]
        if event_type == "llm.human.input":
            cls, who = "human", "用户"
        elif event_type == "llm.ai.response":
            cls, who = "ai", "助手"
        else:
            cls, who = "tool", "工具结果"
        content = message["content"] or ""
        if cls == "tool":
            body_html = f"<details><summary>展开（{len(content)} 字符）</summary><pre>{esc(clip(content, 4000))}</pre></details>"
        else:
            body_html = f'<div class="body">{esc(clip(content, 4000))}</div>'
        rendered.append(
            f"""<div class="msg {cls}">
  <div class="who">{who} · seq {int(message['seq'])} · {fmt_dt(message['created_at'])}</div>
  {body_html}
</div>"""
        )
    if not rendered:
        rendered.append('<div class="muted">这个会话还没有可显示的消息。</div>')

    body = f"""
<div class="back"><a href="/">← 返回运营台</a></div>
<div class="top">
  <div><h1>{esc(clip(title, 80))}</h1>
  <div class="muted">用户 {esc(owner_note)} · 会话 {esc(thread_id)} · 创建于 {fmt_dt(meta['created_at']) if meta else '—'}</div></div>
</div>
{''.join(rendered)}
"""
    return shell(title, body)