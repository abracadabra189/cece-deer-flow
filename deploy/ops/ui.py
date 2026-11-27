"""Shared HTML, formatting and layout for the operations console."""

from __future__ import annotations

import html
import json
import os
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.responses import HTMLResponse

TZ = ZoneInfo(os.environ.get("OPS_TZ", "Asia/Shanghai"))
MAX_DAYS = max(1, int(os.environ.get("OPS_MAX_DAYS", "90")))

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 18px 28px 60px;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", sans-serif;
  color: #1f2937; background: #f7f8fa;
}
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 22px 0 10px; }
.muted { color: #6b7280; font-size: 12px; }
.small { font-size: 12px; }
.nav { display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
  padding: 0 0 14px; margin-bottom: 16px; border-bottom: 1px solid #e5e7eb; }
.nav .brand { font-weight: 600; margin-right: 8px; }
.nav a { color: #4b5563; font-size: 13px; }
.nav a.active { color: #111827; font-weight: 600; }
.nav a:hover { text-decoration: none; color: #111827; }
.top { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; align-items: stretch; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 16px;
  min-width: 120px; flex: 1 1 150px; display: flex; flex-direction: column; justify-content: center; }
.card .n { font-size: 20px; font-weight: 600; }
.card .k { color: #6b7280; font-size: 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; }
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
.warn { background: #fef3c7; color: #92400e; }
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
.hbar-wrap { background: #f1f5f9; border-radius: 4px; height: 10px; overflow: hidden; min-width: 80px; }
.hbar { height: 10px; border-radius: 4px; }
label.inline { flex-direction: row; align-items: center; gap: 6px; }
"""


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


def fmt_day(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%m-%d")
    return str(value)


def fmt_duration(start: Any, end: Any) -> str:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return "—"
    seconds = max(0, int((end - start).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def fmt_seconds(value: Any) -> str:
    try:
        seconds = max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return "—"
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


def fmt_pct(part: Any, total: Any) -> str:
    try:
        p = float(part or 0)
        t = float(total or 0)
    except (TypeError, ValueError):
        return "—"
    if t <= 0:
        return "—"
    return f"{p / t * 100:.1f}%"


def clamp_days(days: int) -> int:
    return max(1, min(MAX_DAYS, days))


def like(value: str) -> str:
    return f"%{value.strip()}%"


def origin_label(value: Any) -> str:
    return {"schedule": "定时任务", "im_channel": "IM", "github": "GitHub", "extension": "扩展", "mcp_notification": "MCP"}.get(str(value or ""), "Web")


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
    label = {"success": "成功", "error": "失败", "timeout": "超时", "interrupted": "中断", "pending": "排队", "running": "运行中"}.get(value, value)
    return f'<span class="badge {cls}">{esc(label)}</span>'


def error_box(exc: Exception) -> str:
    return f'<div class="err"><b>查询失败</b><br>{esc(type(exc).__name__)}: {esc(exc)}</div>'


def hbar(value: Any, maximum: Any, color: str = "#2563eb", width: int = 140) -> str:
    try:
        v = float(value or 0)
        m = float(maximum or 0)
    except (TypeError, ValueError):
        v, m = 0.0, 0.0
    pct = 0 if m <= 0 else max(2, min(100, int(v / m * 100)))
    return f'<div class="hbar-wrap" style="width:{width}px;display:inline-block;vertical-align:middle"><div class="hbar" style="width:{pct}%;background:{color}"></div></div>'


def stacked_bar(ok: int, bad: int, width: int = 140) -> str:
    total = max(1, int(ok) + int(bad))
    ok_pct = int(ok) / total * 100
    bad_pct = int(bad) / total * 100
    return f'<div class="hbar-wrap" style="width:{width}px;display:flex"><div class="hbar" style="width:{ok_pct}%;background:#22c55e"></div><div class="hbar" style="width:{bad_pct}%;background:#ef4444"></div></div>'


NAV_ITEMS = [
    ("runs", "/", "运营台"),
    ("users", "/users", "用户"),
    ("skills", "/skills", "技能"),
    ("errors", "/errors", "错误"),
    ("outliers", "/outliers", "异常"),
    ("trends", "/trends", "趋势"),
]


def nav(active: str = "") -> str:
    links = "".join(f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>' for key, href, label in NAV_ITEMS)
    return f'<div class="nav"><span class="brand">CeCeMate 运营台</span>{links}</div>'


def shell(title: str, body: str, active: str = "") -> HTMLResponse:
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
{nav(active)}
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


def cards_row(items: list[str]) -> str:
    return f'<div class="cards">{"".join(items)}</div>'


def kpi(label: str, value: Any, note: str = "") -> str:
    note_html = f'<div class="muted">{esc(note)}</div>' if note else ""
    return f'<div class="card"><div class="n">{esc(value)}</div><div class="k">{esc(label)}</div>{note_html}</div>'
