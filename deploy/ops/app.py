"""Read-only operations console for DeerFlow.

A standalone service: it does not import the harness or app packages, keeps a
single read-only PostgreSQL connection, and every request carries a statement
timeout. See README.md for deployment and the measured query costs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

from db import DATABASE_URL, PAGE_LIMIT, cached, fetch, resolve_user_ids, user_code_map
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from queries import (
    ERROR_DAILY,
    ERROR_GROUPS,
    ERROR_RECENT,
    OUTLIER_CALLS,
    OUTLIER_SECONDS,
    OUTLIER_STATS,
    OUTLIER_TOKENS,
    SKILL_ACTIVATIONS,
    SKILL_DESCRIBES,
    SKILL_DETAIL,
    SKILL_REFS,
    SKILL_TOTAL,
    SKILLS,
    STALE_RUNS,
    TREND_DAILY,
    TREND_MODELS,
    TREND_ORIGINS,
    TREND_PERCENTILES,
    build_runs_filter,
)
from ui import (
    MAX_DAYS,
    TZ,
    cards_row,
    clamp_days,
    clip,
    error_box,
    esc,
    fmt_day,
    fmt_dt,
    fmt_duration,
    fmt_pct,
    fmt_seconds,
    fmt_tokens,
    hbar,
    kpi,
    origin_label,
    pretty_json,
    shell,
    stacked_bar,
    status_badge,
)

app = FastAPI(title="DeerFlow Ops", docs_url=None, redoc_url=None, openapi_url=None)

THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

ORIGINS = [
    ("", "全部"),
    ("interactive", "Web"),
    ("schedule", "定时任务"),
    ("im_channel", "IM"),
    ("mcp_notification", "MCP"),
    ("extension", "扩展"),
    ("github", "GitHub"),
]


def origin_options(selected: str) -> str:
    return "".join(f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>' for value, label in ORIGINS)


def display_user(user_id: str, emails: dict[str, str], names: dict[str, str]) -> str:
    return names.get(user_id) or emails.get(user_id) or user_id or "—"


def user_labels(row: dict[str, Any], emails: dict[str, str], names: dict[str, str]) -> tuple[str, str]:
    """Display the person's name; fall back to email, then the user ID.

    The MySQL code is deliberately not shown: names are what operators use.
    """
    user_id = str(row.get("user_id") or "")
    email = emails.get(user_id) or str(row.get("email") or "")
    name = names.get(user_id, "")
    return name or email or user_id or "—", email if name and email else ""


async def _tool_counts(run_ids: list[str]) -> dict[str, list[tuple[str, int]]]:
    ids = ",".join(run_ids)
    rows = await fetch(
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
    )
    result: dict[str, list[tuple[str, int]]] = {}
    for row in rows:
        tool = str(row["tool"] or "").strip()
        if tool:
            result.setdefault(str(row["run_id"]), []).append((tool, int(row["n"])))
    return result


async def _error_types(run_ids: list[str]) -> dict[str, str]:
    ids = ",".join(run_ids)
    rows = await fetch(
        """
        SELECT DISTINCT ON (run_id) run_id, event_metadata::jsonb ->> 'error_type' AS error_type
        FROM run_events
        WHERE run_id = ANY(string_to_array(:ids, ','))
          AND event_type IN ('run.error', 'llm.error')
        ORDER BY run_id, seq
        """,
        ids=ids,
    )
    return {str(row["run_id"]): str(row["error_type"]) for row in rows if row["error_type"]}


def extract_skill_usages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["event_type"] != "llm.ai.response":
            continue
        try:
            payload = json.loads(event["content"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        usages = (payload.get("additional_kwargs") or {}).get("skill_usages") or []
        if not isinstance(usages, list):
            continue
        for usage in usages:
            if isinstance(usage, dict) and usage.get("name"):
                seen.setdefault(str(usage["name"]), usage)
    return list(seen.values())


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
    details: int = 1,
) -> HTMLResponse:
    days = clamp_days(days)
    try:
        codes, emails, names = await user_code_map()
        who_ids = resolve_user_ids(who, codes, emails, names) if who.strip() else None
        where_sql, params = build_runs_filter(days=days, user=user, who_ids=who_ids, status=status, origin=origin, model=model, q=q)
        params["limit"] = PAGE_LIMIT
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
        tools_failed = False
        if run_ids:
            if details:
                try:
                    tools_by_run = await cached(("tools", tuple(run_ids)), 60, lambda: _tool_counts(run_ids))
                except Exception:  # noqa: BLE001 - keep the list usable
                    tools_failed = True
            try:
                errors_by_run = await cached(("errors", tuple(run_ids)), 60, lambda: _error_types(run_ids))
            except Exception:  # noqa: BLE001 - optional enrichment
                errors_by_run = {}
    except Exception as exc:  # noqa: BLE001 - rendered in the page
        return shell("运营台", error_box(exc), "runs")

    cards = cards_row(
        [
            kpi(f"runs（近 {days} 天）", int(stats["runs"] or 0)),
            kpi("失败 / 超时", int(stats["failed"] or 0)),
            kpi("tokens", fmt_tokens(stats["tokens"])),
            kpi("用户", int(stats["users"] or 0)),
            kpi("会话", int(stats["threads"] or 0)),
        ]
    )

    body_rows = []
    for row in rows:
        run_id = str(row["run_id"])
        question = clip(row["first_human_message"], 140) or "(无问题文本)"
        answer = clip(row["last_ai_message"], 90)
        error = clip(row["error"], 120)
        label, secondary = user_labels(row, emails, names)
        tools = " ".join(f"{tool}×{count}" for tool, count in tools_by_run.get(run_id, [])[:4])
        if not details:
            tools_cell = '<span class="muted">未加载</span>'
        elif tools:
            tools_cell = esc(clip(tools, 36))
        else:
            tools_cell = '<span class="muted">加载失败</span>' if tools_failed else "—"
        error_type = errors_by_run.get(run_id, "")
        trace_id = str(row["trace_id"] or "")
        assistant = str(row["assistant_id"] or "")
        assistant_note = f'<div class="muted">{esc(assistant)}</div>' if assistant and assistant != "lead_agent" else ""
        run_cell = f'<a href="/runs/{esc(run_id)}" title="{esc(run_id)}">{esc(run_id[:8])}…</a>'
        trace_cell = f'<code class="trace" data-copy="{esc(trace_id)}" title="{esc(trace_id)}">{esc(trace_id[:8])}…</code>' if trace_id else '<span class="muted">—</span>'
        body_rows.append(
            f"""<tr>
  <td class="nowrap">{fmt_dt(row["created_at"])}<div class="muted">{esc(origin_label(row["origin_kind"]))}</div></td>
  <td class="nowrap"><span title="{esc(secondary or label)}">{esc(label)}</span>
      {f'<div class="muted">{esc(secondary)}</div>' if secondary else ""}</td>
  <td><a href="/threads/{esc(row["thread_id"])}">{esc(clip(row["display_name"], 40) or "(未命名会话)")}</a>
      <div class="q">{esc(question)}</div>
      {f'<div class="answer">答：{esc(answer)}</div>' if answer else ""}
      {f'<div class="answer">错误：{esc(error)}</div>' if error else ""}
  </td>
  <td class="nowrap">{status_badge(row["status"])}
      {f'<div class="muted">{esc(error_type)}</div>' if error_type else ""}</td>
  <td class="nowrap">{fmt_duration(row["created_at"], row["updated_at"])}</td>
  <td class="nowrap" title="in {fmt_tokens(row["total_input_tokens"])} / out {fmt_tokens(row["total_output_tokens"])}">{fmt_tokens(row["total_tokens"])}</td>
  <td class="nowrap">{int(row["llm_call_count"] or 0)}</td>
  <td>{tools_cell or "—"}</td>
  <td class="nowrap">{esc(row["model_name"] or "—")}{assistant_note}</td>
  <td class="nowrap"><div class="muted">run</div>{run_cell}<div class="muted">trace</div>{trace_cell}</td>
</tr>"""
        )
    if not body_rows:
        body_rows.append('<tr><td colspan="10" class="muted">没有匹配的记录</td></tr>')

    base_params: dict[str, Any] = {"days": days}
    for key, value in (("user", user), ("who", who), ("status", status), ("origin", origin), ("model", model), ("q", q)):
        if value:
            base_params[key] = value
    detail_href = "/?" + urlencode({**base_params, "details": 1})
    hide_href = "/?" + urlencode({**base_params, "details": 0})

    who_notice = ""
    if who.strip() and not who_ids:
        who_notice = f'<div class="err">没有匹配「{esc(who)}」的用户（按名字 / 编码 / 邮箱匹配）</div>'

    tool_header = f'<a href="{hide_href}">隐藏</a>' if details else f'<a href="{detail_href}">加载</a>'

    body = f"""
<div class="top">
  <div><h1>运营台</h1><div class="muted">只读 · 数据截至 {datetime.now(TZ).strftime("%Y-%m-%d %H:%M")}</div></div>
</div>
{cards}
{who_notice}
<form class="filters" method="get">
  <input type="hidden" name="user" value="{esc(user)}">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <label>名字 / 编码 / 邮箱<input name="who" value="{esc(who)}" placeholder="如 张三 / sh02311" style="width:200px"></label>
  <label>状态
    <select name="status">
      <option value="" {"selected" if not status else ""}>全部</option>
      <option value="success" {"selected" if status == "success" else ""}>成功</option>
      <option value="error" {"selected" if status == "error" else ""}>失败</option>
      <option value="running" {"selected" if status == "running" else ""}>运行中</option>
    </select>
  </label>
  <label>来源<select name="origin">{origin_options(origin)}</select></label>
  <label>模型<input name="model" value="{esc(model)}" placeholder="可留空" style="width:150px"></label>
  <label>关键词<input name="q" value="{esc(q)}" placeholder="搜索问题 / 回答" style="width:180px"></label>
  <label>工具详情
    <select name="details">
      <option value="1" {"selected" if details else ""}>显示（较慢）</option>
      <option value="0" {"selected" if not details else ""}>隐藏</option>
    </select>
  </label>
  <button type="submit">筛选</button>
</form>
<div style="overflow-x:auto">
<table>
<thead><tr><th>时间</th><th>用户</th><th>会话 / 问题</th><th>状态</th>
<th>耗时</th><th>tokens</th><th>调用</th><th>工具 {tool_header}</th><th>模型</th><th>run / trace</th></tr></thead>
<tbody>{"".join(body_rows)}</tbody>
</table>
</div>
<div class="muted" style="margin-top:8px">最多显示 {PAGE_LIMIT} 条；缩小时间范围可看到更早的记录。点击 run 看这一轮的完整事件，点击 trace 可复制。工具详情默认加载（约有 60 秒缓存）。</div>
"""
    return shell("运营台", body, "runs")


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
        codes, _, names = await user_code_map()
    except Exception as exc:  # noqa: BLE001
        return shell("用户", error_box(exc), "users")

    if who.strip():
        needle = who.strip().lower()
        rows = [row for row in rows if needle in str(row["email"] or "").lower() or needle in codes.get(str(row["id"]), "") or needle in names.get(str(row["id"]), "").lower()]

    body_rows = []
    for row in rows:
        user_id = str(row["id"])
        email = str(row["email"] or "")
        name = names.get(user_id, "")
        label = name or email or user_id
        detail = email if name and email else ""
        secondary = f'<div class="muted">{esc(detail)}</div>' if detail else ""
        body_rows.append(
            f"""<tr>
  <td><a href="/?user={esc(user_id)}">{esc(label)}</a>{secondary}</td>
  <td class="nowrap">{esc(row["system_role"])}</td>
  <td class="nowrap">{"已禁用" if row["disabled"] else "正常"}</td>
  <td class="nowrap">{int(row["runs"] or 0)}</td>
  <td class="nowrap">{fmt_tokens(row["tokens"])}</td>
  <td class="nowrap">{int(row["failed"] or 0)}</td>
  <td class="nowrap">{fmt_dt(row["last_run"])}</td>
</tr>"""
        )
    if not body_rows:
        body_rows.append(f'<tr><td colspan="7" class="muted">{"没有匹配的用户" if who.strip() else "没有用户"}</td></tr>')

    body = f"""
<div class="top"><h1>用户</h1><div class="muted">近 {days} 天 · 按活跃度排序</div></div>
<form class="filters" method="get">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <label>名字 / 编码 / 邮箱<input name="who" value="{esc(who)}" placeholder="如 张三 / sh02311" style="width:220px"></label>
  <button type="submit">筛选</button>
</form>
<table>
<thead><tr><th>用户</th><th>角色</th><th>状态</th><th>runs</th><th>tokens</th><th>失败</th><th>最近活跃</th></tr></thead>
<tbody>{"".join(body_rows)}</tbody>
</table>
"""
    return shell("用户", body, "users")


@app.get("/errors", response_class=HTMLResponse)
async def errors(
    days: int = Query(7),
    who: str = "",
    user: str = "",
    origin: str = "",
    model: str = "",
) -> HTMLResponse:
    days = clamp_days(days)
    try:
        codes, emails, names = await user_code_map()
        who_ids = resolve_user_ids(who, codes, emails, names) if who.strip() else None
        where_sql, params = build_runs_filter(days=days, user=user, who_ids=who_ids, origin=origin, model=model)
        groups = await cached(("err_groups", days, user, who_ids, origin, model), 60, lambda: fetch(ERROR_GROUPS.replace("__WHERE__", where_sql), **params))
        recent = await cached(("err_recent", days, user, who_ids, origin, model), 60, lambda: fetch(ERROR_RECENT.replace("__WHERE__", where_sql), **params))
        daily = await cached(("err_daily", days, user, who_ids, origin, model), 60, lambda: fetch(ERROR_DAILY.replace("__WHERE__", where_sql), **params))
    except Exception as exc:  # noqa: BLE001
        return shell("错误", error_box(exc), "errors")

    total_bad = sum(int(row["bad"] or 0) for row in daily)
    total_runs = sum(int(row["total"] or 0) for row in daily)
    cards = cards_row(
        [
            kpi("失败 / 中断", total_bad),
            kpi("失败率", fmt_pct(total_bad, total_runs)),
            kpi("错误类型", len(groups)),
            kpi("runs", total_runs),
        ]
    )

    group_rows = []
    for row in groups:
        group_rows.append(
            f"""<tr>
  <td>{esc(clip(row["error_type"], 80))}</td>
  <td class="nowrap">{int(row["runs"] or 0)}</td>
  <td class="nowrap">{int(row["users"] or 0)}</td>
  <td class="nowrap">{fmt_dt(row["last_seen"])}</td>
  <td class="nowrap">{f'<a href="/runs/{esc(row["sample_run"])}">示例</a>' if row["sample_run"] else "—"}</td>
</tr>"""
        )
    if not group_rows:
        group_rows.append(f'<tr><td colspan="5" class="muted">近 {days} 天没有失败</td></tr>')

    daily_rows = []
    for row in daily:
        daily_rows.append(
            f"""<tr>
  <td class="nowrap">{fmt_day(row["day"])}</td>
  <td class="nowrap">{int(row["total"] or 0)}</td>
  <td class="nowrap">{stacked_bar(int(row["total"] or 0) - int(row["bad"] or 0), int(row["bad"] or 0))}
      <span class="muted">{int(row["bad"] or 0)} 失败</span></td>
</tr>"""
        )

    recent_rows = []
    for row in recent:
        label, _ = user_labels(row, emails, names)
        recent_rows.append(
            f"""<tr>
  <td class="nowrap">{fmt_dt(row["created_at"])}</td>
  <td class="nowrap">{esc(label)}</td>
  <td><a href="/runs/{esc(row["run_id"])}">{esc(clip(row["first_human_message"], 100) or "(无问题文本)")}</a>
      <div class="answer">{esc(clip(row["error"], 140))}</div></td>
  <td class="nowrap">{esc(clip(row["error_type"], 40) or "—")}</td>
  <td class="nowrap">{status_badge(row["status"])}</td>
  <td class="nowrap">{esc(row["model_name"] or "—")}</td>
</tr>"""
        )
    if not recent_rows:
        recent_rows.append('<tr><td colspan="6" class="muted">没有记录</td></tr>')

    body = f"""
<div class="top"><h1>错误</h1><div class="muted">近 {days} 天 · 失败与中断</div></div>
{cards}
<form class="filters" method="get">
  <input type="hidden" name="user" value="{esc(user)}">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <label>名字 / 编码 / 邮箱<input name="who" value="{esc(who)}" style="width:200px"></label>
  <label>来源<select name="origin">{origin_options(origin)}</select></label>
  <label>模型<input name="model" value="{esc(model)}" style="width:150px"></label>
  <button type="submit">筛选</button>
</form>
<div class="grid">
  <div>
    <h2>按错误类型</h2>
    <table><thead><tr><th>错误</th><th>runs</th><th>用户</th><th>最近</th><th>示例</th></tr></thead>
    <tbody>{"".join(group_rows)}</tbody></table>
  </div>
  <div>
    <h2>按天失败</h2>
    <table><thead><tr><th>日期</th><th>runs</th><th>成功 / 失败</th></tr></thead>
    <tbody>{"".join(daily_rows) or '<tr><td colspan="3" class="muted">没有数据</td></tr>'}</tbody></table>
  </div>
</div>
<h2>最近失败</h2>
<div style="overflow-x:auto"><table>
<thead><tr><th>时间</th><th>用户</th><th>问题 / 错误</th><th>类型</th><th>状态</th><th>模型</th></tr></thead>
<tbody>{"".join(recent_rows)}</tbody></table></div>
"""
    return shell("错误", body, "errors")


@app.get("/outliers", response_class=HTMLResponse)
async def outliers(days: int = Query(7), who: str = "", user: str = "", model: str = "") -> HTMLResponse:
    days = clamp_days(days)
    try:
        codes, emails, names = await user_code_map()
        who_ids = resolve_user_ids(who, codes, emails, names) if who.strip() else None
        where_sql, params = build_runs_filter(days=days, user=user, who_ids=who_ids, model=model)
        stats = (await cached(("out_stats", days, user, who_ids, model), 60, lambda: fetch(OUTLIER_STATS.replace("__WHERE__", where_sql), **params)))[0]
        by_tokens = await cached(("out_tokens", days, user, who_ids, model), 60, lambda: fetch(OUTLIER_TOKENS.replace("__WHERE__", where_sql), **params))
        by_seconds = await cached(("out_seconds", days, user, who_ids, model), 60, lambda: fetch(OUTLIER_SECONDS.replace("__WHERE__", where_sql), **params))
        by_calls = await cached(("out_calls", days, user, who_ids, model), 60, lambda: fetch(OUTLIER_CALLS.replace("__WHERE__", where_sql), **params))
        stale = await cached(("out_stale", days, user, who_ids, model), 60, lambda: fetch(STALE_RUNS.replace("__WHERE__", where_sql), **params))
    except Exception as exc:  # noqa: BLE001
        return shell("异常", error_box(exc), "outliers")

    cards = cards_row(
        [
            kpi("最大 tokens", fmt_tokens(stats["max_tokens"])),
            kpi("最长耗时", fmt_seconds(stats["max_seconds"])),
            kpi("最多调用", int(stats["max_calls"] or 0)),
            kpi("疑似卡死", int(stats["stale"] or 0)),
        ]
    )

    def table(rows: list[dict[str, Any]]) -> str:
        body_rows = []
        for row in rows:
            label, _ = user_labels(row, emails, names)
            body_rows.append(
                f"""<tr>
  <td class="nowrap">{fmt_dt(row["created_at"])}</td>
  <td class="nowrap">{esc(label)}</td>
  <td><a href="/runs/{esc(row["run_id"])}">{esc(clip(row["first_human_message"], 90) or "(无问题文本)")}</a></td>
  <td class="nowrap">{status_badge(row["status"])}</td>
  <td class="nowrap">{fmt_tokens(row["total_tokens"])}</td>
  <td class="nowrap">{int(row["llm_call_count"] or 0)}</td>
  <td class="nowrap">{fmt_duration(row["created_at"], row["updated_at"])}</td>
</tr>"""
            )
        if not body_rows:
            body_rows.append('<tr><td colspan="7" class="muted">没有数据</td></tr>')
        return f"""<div style="overflow-x:auto"><table>
<thead><tr><th>时间</th><th>用户</th><th>问题</th><th>状态</th><th>tokens</th><th>调用</th><th>耗时</th></tr></thead>
<tbody>{"".join(body_rows)}</tbody></table></div>"""

    body = f"""
<div class="top"><h1>异常</h1><div class="muted">近 {days} 天 · 大 run、长 run、疑似卡死</div></div>
{cards}
<form class="filters" method="get">
  <input type="hidden" name="user" value="{esc(user)}">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <label>名字 / 编码 / 邮箱<input name="who" value="{esc(who)}" style="width:200px"></label>
  <label>模型<input name="model" value="{esc(model)}" style="width:150px"></label>
  <button type="submit">筛选</button>
</form>
<h2>按 tokens</h2>{table(by_tokens)}
<h2>按耗时</h2>{table(by_seconds)}
<h2>按模型调用次数</h2>{table(by_calls)}
<h2>疑似卡死 / 超长</h2>{table(stale)}
"""
    return shell("异常", body, "outliers")


@app.get("/trends", response_class=HTMLResponse)
async def trends(days: int = Query(14), who: str = "", user: str = "", origin: str = "", model: str = "") -> HTMLResponse:
    days = clamp_days(days)
    try:
        codes, emails, names = await user_code_map()
        who_ids = resolve_user_ids(who, codes, emails, names) if who.strip() else None
        where_sql, params = build_runs_filter(days=days, user=user, who_ids=who_ids, origin=origin, model=model)
        daily = await cached(("trend_daily", days, user, who_ids, origin, model), 60, lambda: fetch(TREND_DAILY.replace("__WHERE__", where_sql), **params))
        percentiles = await cached(("trend_pct", days, user, who_ids, origin, model), 60, lambda: fetch(TREND_PERCENTILES.replace("__WHERE__", where_sql), **params))
        models = await cached(("trend_models", days, user, who_ids, origin, model), 60, lambda: fetch(TREND_MODELS.replace("__WHERE__", where_sql), **params))
        origins = await cached(("trend_origins", days, user, who_ids, origin, model), 60, lambda: fetch(TREND_ORIGINS.replace("__WHERE__", where_sql), **params))
    except Exception as exc:  # noqa: BLE001
        return shell("趋势", error_box(exc), "trends")

    total_runs = sum(int(row["runs"] or 0) for row in daily)
    total_bad = sum(int(row["bad"] or 0) for row in daily)
    total_tokens = sum(int(row["tokens"] or 0) for row in daily)
    active_users = max((int(row["users"] or 0) for row in daily), default=0)
    pct = {str(row["day"]): row for row in percentiles}

    cards = cards_row(
        [
            kpi("runs", total_runs),
            kpi("tokens", fmt_tokens(total_tokens)),
            kpi("失败率", fmt_pct(total_bad, total_runs)),
            kpi("单日最多用户", active_users),
        ]
    )

    max_tokens = max((int(row["tokens"] or 0) for row in daily), default=0)
    daily_rows = []
    for row in daily:
        key = str(row["day"])
        p = pct.get(key, {})
        daily_rows.append(
            f"""<tr>
  <td class="nowrap">{fmt_day(row["day"])}</td>
  <td class="nowrap">{int(row["runs"] or 0)}</td>
  <td>{stacked_bar(int(row["ok"] or 0), int(row["bad"] or 0))}</td>
  <td>{hbar(row["tokens"], max_tokens, "#2563eb")} <span class="muted">{fmt_tokens(row["tokens"])}</span></td>
  <td class="nowrap">{int(row["users"] or 0)}</td>
  <td class="nowrap">{fmt_seconds(p.get("p50"))}</td>
  <td class="nowrap">{fmt_seconds(p.get("p95"))}</td>
</tr>"""
        )
    if not daily_rows:
        daily_rows.append('<tr><td colspan="7" class="muted">没有数据</td></tr>')

    model_rows = [f"<tr><td>{esc(row['model'])}</td><td class='nowrap'>{int(row['runs'] or 0)}</td><td class='nowrap'>{fmt_tokens(row['tokens'])}</td></tr>" for row in models] or ['<tr><td colspan="3" class="muted">没有数据</td></tr>']
    origin_rows = [f"<tr><td>{esc(origin_label(row['origin'] if row['origin'] != 'interactive' else ''))}</td><td class='nowrap'>{int(row['runs'] or 0)}</td></tr>" for row in origins] or [
        '<tr><td colspan="2" class="muted">没有数据</td></tr>'
    ]

    body = f"""
<div class="top"><h1>趋势</h1><div class="muted">近 {days} 天</div></div>
{cards}
<form class="filters" method="get">
  <input type="hidden" name="user" value="{esc(user)}">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <label>名字 / 编码 / 邮箱<input name="who" value="{esc(who)}" style="width:200px"></label>
  <label>来源<select name="origin">{origin_options(origin)}</select></label>
  <label>模型<input name="model" value="{esc(model)}" style="width:150px"></label>
  <button type="submit">筛选</button>
</form>
<h2>按天</h2>
<div style="overflow-x:auto"><table>
<thead><tr><th>日期</th><th>runs</th><th>成功 / 失败</th><th>tokens</th><th>用户</th><th>p50</th><th>p95</th></tr></thead>
<tbody>{"".join(daily_rows)}</tbody></table></div>
<div class="grid">
  <div><h2>按模型</h2><table><thead><tr><th>模型</th><th>runs</th><th>tokens</th></tr></thead><tbody>{"".join(model_rows)}</tbody></table></div>
  <div><h2>按来源</h2><table><thead><tr><th>来源</th><th>runs</th></tr></thead><tbody>{"".join(origin_rows)}</tbody></table></div>
</div>
"""
    return shell("趋势", body, "trends")


@app.get("/skills", response_class=HTMLResponse)
async def skills(days: int = Query(30)) -> HTMLResponse:
    days = clamp_days(days)
    try:
        usage = await cached(("skills", days), 60, lambda: fetch(SKILLS, days=days))
        total = (await cached(("skill_total", days), 60, lambda: fetch(SKILL_TOTAL, days=days)))[0]
        refs = await cached(("skill_refs", days), 60, lambda: fetch(SKILL_REFS, days=days))
        acts = await cached(("skill_acts", days), 60, lambda: fetch(SKILL_ACTIVATIONS, days=days))
        describes = (await cached(("skill_describes", days), 60, lambda: fetch(SKILL_DESCRIBES, days=days)))[0]
    except Exception as exc:  # noqa: BLE001
        return shell("技能", error_box(exc), "skills")

    ref_map = {str(row["skill"]): int(row["runs"] or 0) for row in refs}
    act_map = {str(row["skill"]): int(row["runs"] or 0) for row in acts}
    top_runs = max((int(row["runs"] or 0) for row in usage), default=0)
    total_loaded = int(total["runs"] or 0)
    cards = cards_row(
        [
            kpi("加载 run 数", total_loaded),
            kpi("技能数", int(total["skills"] or 0)),
            kpi("Top 技能占比", fmt_pct(top_runs, total_loaded)),
            kpi("describe 调用", int(describes["n"] or 0)),
        ]
    )

    body_rows = []
    for row in usage:
        skill = str(row["skill"])
        label = quote(skill, safe="")
        body_rows.append(
            f"""<tr>
  <td><a href="/skills/{label}">{esc(skill)}</a></td>
  <td class="nowrap">{esc(row["category"] or "—")}</td>
  <td class="nowrap">{esc(row["activation"] or "—")}</td>
  <td class="nowrap">{int(row["runs"] or 0)}</td>
  <td>{hbar(row["runs"], top_runs)}</td>
  <td class="nowrap">{ref_map.get(skill, 0)}</td>
  <td class="nowrap">{act_map.get(skill, 0)}</td>
  <td class="nowrap">{fmt_dt(row["last_used"])}</td>
</tr>"""
        )
    if not body_rows:
        body_rows.append(f'<tr><td colspan="8" class="muted">近 {days} 天没有技能加载记录</td></tr>')

    body = f"""
<div class="top"><h1>技能</h1><div class="muted">近 {days} 天 · 以实际加载（skill_usages）为准</div></div>
{cards}
<form class="filters" method="get">
  <label>天数<input name="days" type="number" min="1" max="{MAX_DAYS}" value="{days}" style="width:80px"></label>
  <button type="submit">刷新</button>
</form>
<table>
<thead><tr><th>技能</th><th>分类</th><th>激活方式</th><th>使用 run</th><th>占比</th><th>显式引用</th><th>激活事件</th><th>最近使用</th></tr></thead>
<tbody>{"".join(body_rows)}</tbody>
</table>
<div class="muted" style="margin-top:8px">“加载”来自 AI 消息的 additional_kwargs.skill_usages；同一次 run 内重复加载会去重，子 Agent 的技能加载不计入。</div>
"""
    return shell("技能", body, "skills")


@app.get("/skills/{name}", response_class=HTMLResponse)
async def skill_detail(name: str, days: int = Query(30)) -> HTMLResponse:
    days = clamp_days(days)
    if not SKILL_NAME_RE.match(name):
        return shell("技能", '<div class="err">非法的技能名</div>', "skills")
    try:
        rows = await cached(("skill_detail", name, days), 60, lambda: fetch(SKILL_DETAIL, days=days, skill=name))
        _, emails, names = await user_code_map()
    except Exception as exc:  # noqa: BLE001
        return shell("技能", error_box(exc), "skills")

    if not rows:
        return shell("技能", f'<div class="err">近 {days} 天没有「{esc(name)}」的加载记录</div>', "skills")

    per_day: dict[str, int] = {}
    per_user: dict[str, int] = {}
    for row in rows:
        day = str(row["created_at"].date()) if row["created_at"] else "—"
        per_day[day] = per_day.get(day, 0) + 1
        uid = str(row["user_id"] or "")
        per_user[display_user(uid, emails, names)] = per_user.get(display_user(uid, emails, names), 0) + 1
    max_day = max(per_day.values(), default=0)
    day_rows = [f"<tr><td class='nowrap'>{esc(day)}</td><td class='nowrap'>{count}</td><td>{hbar(count, max_day)}</td></tr>" for day, count in sorted(per_day.items())]
    run_rows = [
        f"""<tr>
  <td class="nowrap">{fmt_dt(row["created_at"])}</td>
  <td class="nowrap">{esc(display_user(str(row["user_id"] or ""), emails, names))}</td>
  <td class="nowrap">{esc(row["category"] or "—")}</td>
  <td class="nowrap">{esc(row["activation"] or "—")}</td>
  <td class="nowrap"><a href="/runs/{esc(row["run_id"])}">{esc(row["run_id"][:8])}…</a></td>
</tr>"""
        for row in rows[:100]
    ]

    cards = cards_row(
        [
            kpi("run 数", len(rows)),
            kpi("用户数", len(per_user)),
            kpi("活跃天数", len(per_day)),
            kpi("最近使用", fmt_dt(rows[0]["created_at"])),
        ]
    )
    body = f"""
<div class="back"><a href="/skills">← 返回技能</a></div>
<div class="top"><h1>{esc(name)}</h1><div class="muted">近 {days} 天</div></div>
{cards}
<div class="grid">
  <div><h2>按天</h2><table><thead><tr><th>日期</th><th>runs</th><th></th></tr></thead><tbody>{"".join(day_rows)}</tbody></table></div>
  <div><h2>按用户</h2><table><thead><tr><th>用户</th><th>runs</th></tr></thead>
  <tbody>{"".join(f"<tr><td>{esc(uid or '—')}</td><td>{count}</td></tr>" for uid, count in sorted(per_user.items(), key=lambda item: -item[1]))}</tbody></table></div>
</div>
<h2>最近 run</h2>
<div style="overflow-x:auto"><table>
<thead><tr><th>时间</th><th>用户</th><th>分类</th><th>激活</th><th>run</th></tr></thead>
<tbody>{"".join(run_rows)}</tbody></table></div>
"""
    return shell(name, body, "skills")


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(run_id: str) -> HTMLResponse:
    if not RUN_ID_RE.match(run_id):
        return shell("Run", '<div class="err">非法的 run ID</div>', "runs")
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
            return shell("Run", f'<div class="err">找不到 run {esc(run_id)}</div>', "runs")
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
        _, emails, names = await user_code_map()
    except Exception as exc:  # noqa: BLE001
        return shell("Run", error_box(exc), "runs")

    label, secondary = user_labels(run, emails, names)
    owner_note = f"{label}（{secondary}）" if secondary else label
    trace_id = str((run.get("metadata_json") or {}).get("deerflow_trace_id") or "")
    duration = fmt_duration(run["created_at"], run["updated_at"])
    assistant = str(run.get("assistant_id") or "")
    trace_cell = f'<code class="trace" data-copy="{esc(trace_id)}" title="{esc(trace_id)}">{esc(trace_id)}</code>' if trace_id else '<span class="muted">—</span>'
    run_cell = f'<code class="trace" data-copy="{esc(run_id)}" title="{esc(run_id)}">{esc(run_id)}</code>'

    cards = cards_row(
        [
            kpi("耗时", duration),
            kpi("tokens", fmt_tokens(run["total_tokens"]), f"{fmt_tokens(run['total_input_tokens'])} in / {fmt_tokens(run['total_output_tokens'])} out"),
            kpi("模型调用", int(run["llm_call_count"] or 0)),
            kpi("消息数", int(run["message_count"] or 0)),
            kpi("模型", run["model_name"] or "—"),
        ]
    )

    error_items: list[str] = []
    if run["error"]:
        error_items.append(
            f"""<div class="msg error">
  <div class="who">runs.error · stop_reason {esc(run["stop_reason"] or "—")}</div>
  <div class="body">{esc(clip(run["error"], 4000))}</div>
</div>"""
        )
    for event in events:
        if event["event_type"] not in ("run.error", "llm.error"):
            continue
        metadata = event["event_metadata"] or {}
        detail_lines = [f"{key}: {metadata.get(key)}" for key in ("error_type", "provider", "model", "caller", "request_chars", "request_message_count", "request_started_at") if metadata.get(key) is not None]
        detail = "\n".join(detail_lines) or clip(event["content"], 2000)
        error_items.append(
            f"""<div class="msg error">
  <div class="who">{esc(event["event_type"])} · seq {int(event["seq"])} · {fmt_dt(event["created_at"])}</div>
  <div class="body">{esc(detail)}</div>
  <details><summary>原始 metadata</summary><pre>{esc(pretty_json(metadata))}</pre></details>
</div>"""
        )
    error_block = ("<h2>错误</h2>" + "".join(error_items)) if error_items else ""

    loaded = extract_skill_usages(events)
    skill_rows = [
        f"""<tr>
  <td>{esc(usage.get("name") or "—")}</td>
  <td class="nowrap">{esc(usage.get("category") or "—")}</td>
  <td class="nowrap">{esc(usage.get("activation") or "—")}</td>
  <td class="muted">{esc(clip(usage.get("path"), 80))}</td>
</tr>"""
        for usage in loaded
    ]
    skills_block = f"<h2>本轮加载的技能</h2><table><thead><tr><th>技能</th><th>分类</th><th>激活</th><th>路径</th></tr></thead><tbody>{''.join(skill_rows)}</tbody></table>" if skill_rows else ""

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
  <div class="who">{esc(who)} · seq {int(event["seq"])} · {fmt_dt(event["created_at"])}</div>
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
    <div class="muted">用户 {esc(owner_note)} · 会话 {esc(thread_id)} · {fmt_dt(run["created_at"])}</div>
    <div class="muted">run {run_cell} · trace {trace_cell}</div>
    {f'<div class="muted">agent {esc(assistant)} · 来源 {esc(origin_label(run["origin_kind"]))}</div>' if assistant else ""}
  </div>
  <div>{status_badge(run["status"])}</div>
</div>
{cards}
{error_block}
{skills_block}
<h2>事件时间线（{len(events)} 条）</h2>
{"".join(rendered)}
"""
    return shell(title, body, "runs")


@app.get("/threads/{thread_id}", response_class=HTMLResponse)
async def thread(thread_id: str) -> HTMLResponse:
    if not THREAD_ID_RE.match(thread_id):
        return shell("会话", '<div class="err">非法的会话 ID</div>', "runs")
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
        _, emails, names = await user_code_map()
    except Exception as exc:  # noqa: BLE001
        return shell("会话", error_box(exc), "runs")

    meta = meta_rows[0] if meta_rows else None
    title = (meta["display_name"] if meta else None) or thread_id
    owner_id = str(meta["user_id"] or "") if meta else ""
    owner_email = emails.get(owner_id) or (meta["email"] if meta else "") or ""
    owner_name = names.get(owner_id, "")
    owner = owner_name or owner_email or owner_id or "—"
    owner_note = f"{owner_name}（{owner_email}）" if owner_name and owner_email else owner

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
  <div class="who">{who} · seq {int(message["seq"])} · {fmt_dt(message["created_at"])}</div>
  {body_html}
</div>"""
        )
    if not rendered:
        rendered.append('<div class="muted">这个会话还没有可显示的消息。</div>')

    body = f"""
<div class="back"><a href="/">← 返回运营台</a></div>
<div class="top">
  <div><h1>{esc(clip(title, 80))}</h1>
  <div class="muted">用户 {esc(owner_note)} · 会话 {esc(thread_id)} · 创建于 {fmt_dt(meta["created_at"]) if meta else "—"}</div></div>
</div>
{"".join(rendered)}
"""
    return shell(title, body, "runs")
