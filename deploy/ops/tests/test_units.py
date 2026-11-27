"""Unit tests for the operations console.

These run without a database. They cover the shared formatters, the filter
builder and the skill-usage parser; page rendering is exercised manually against
the read-only database.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import resolve_user_ids  # noqa: E402
from queries import build_runs_filter  # noqa: E402
from ui import (  # noqa: E402
    clamp_days,
    clip,
    fmt_day,
    fmt_duration,
    fmt_pct,
    fmt_seconds,
    fmt_tokens,
)

from app import app, extract_skill_usages  # noqa: E402


def test_fmt_duration() -> None:
    start = datetime(2026, 1, 1, 12, 0, 0)
    assert fmt_duration(start, start + timedelta(seconds=42)) == "42s"
    assert fmt_duration(start, start + timedelta(seconds=192)) == "3m12s"
    assert fmt_duration(start, start + timedelta(seconds=3900)) == "1h05m"
    assert fmt_duration(None, start) == "—"


def test_fmt_tokens_and_pct() -> None:
    assert fmt_tokens(999) == "999"
    assert fmt_tokens(12_000) == "12.0K"
    assert fmt_tokens(2_500_000) == "2.5M"
    assert fmt_pct(1, 4) == "25.0%"
    assert fmt_pct(1, 0) == "—"
    assert fmt_seconds(192) == "3m12s"


def test_clip_and_days() -> None:
    assert clip("  a \n b  ") == "a b"
    assert clip("abcdef", 3) == "abc…"
    assert clamp_days(0) == 1
    assert clamp_days(10_000) <= 90


def test_fmt_day_accepts_date() -> None:
    assert fmt_day(date(2026, 11, 26)) == "11-26"
    assert fmt_day(datetime(2026, 11, 26, 12, 0)) == "11-26"


def test_filter_builder() -> None:
    where, params = build_runs_filter(
        days=7,
        user="u1",
        who_ids="u2,u3",
        status="error",
        origin="interactive",
        model="deepseek",
        q="合同",
    )
    assert "r.user_id = :user" in where
    assert "r.user_id = ANY(string_to_array(:who_ids, ','))" in where
    assert "r.status = :status" in where
    assert "r.origin_kind IS NULL" in where
    assert "r.model_name ILIKE :model" in where
    assert params["who_ids"] == "u2,u3"
    assert params["model"] == "%deepseek%"
    assert params["q"] == "%合同%"

    where2, params2 = build_runs_filter(days=1, who_ids=None)
    assert "who_ids" not in params2
    assert "operation_kind = 'run'" in where2


def test_resolve_user_ids() -> None:
    codes = {"u1": "sh001"}
    emails = {"u1": "sh001@users.deerflow.internal", "u2": "781907885@qq.com"}
    names = {"u1": "张三"}
    assert resolve_user_ids("张三", codes, emails, names) == "u1"
    assert resolve_user_ids("sh001", codes, emails, names) == "u1"
    assert resolve_user_ids("781907885", codes, emails, names) == "u2"
    assert resolve_user_ids("nobody", codes, emails, names) == ""
    assert resolve_user_ids("", codes, emails, names) == ""


def test_extract_skill_usages_dedupes() -> None:
    def ai(usages):
        return {
            "event_type": "llm.ai.response",
            "content": json.dumps({"additional_kwargs": {"skill_usages": usages}}),
        }

    events = [
        ai([{"name": "a", "category": "public"}, {"name": "b"}]),
        ai([{"name": "a", "category": "public"}]),
        {"event_type": "llm.human.input", "content": "{}"},
        {"event_type": "llm.ai.response", "content": "not json"},
    ]
    usages = extract_skill_usages(events)
    assert [u["name"] for u in usages] == ["a", "b"]


def test_routes_registered() -> None:
    paths = {route.path for route in app.routes}
    expected = {
        "/",
        "/users",
        "/errors",
        "/outliers",
        "/trends",
        "/skills",
        "/skills/{name}",
        "/runs/{run_id}",
        "/threads/{thread_id}",
        "/healthz",
    }
    assert expected <= paths
