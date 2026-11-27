"""SQL used by the operations console.

All statements are read-only. ``build_runs_filter`` is the single place that
turns the shared filters into a WHERE clause, so the pages cannot drift.
"""

from __future__ import annotations

from typing import Any


def build_runs_filter(
    *,
    days: int,
    user: str = "",
    who_ids: str | None = None,
    status: str = "",
    origin: str = "",
    model: str = "",
    q: str = "",
    alias: str = "r",
) -> tuple[str, dict[str, Any]]:
    """Return ``(where_sql, params)`` for the common run filters.

    ``who_ids=None`` means "no owner filter"; an empty string means "the name
    resolved to nobody", which must match nothing.
    """
    where = [
        f"{alias}.operation_kind = 'run'",
        f"{alias}.created_at >= now() - make_interval(days => CAST(:days AS int))",
    ]
    params: dict[str, Any] = {"days": days}
    if user:
        where.append(f"{alias}.user_id = :user")
        params["user"] = user
    if who_ids is not None:
        where.append(f"{alias}.user_id = ANY(string_to_array(:who_ids, ','))")
        params["who_ids"] = who_ids
    if status:
        where.append(f"{alias}.status = :status")
        params["status"] = status
    if origin == "interactive":
        where.append(f"{alias}.origin_kind IS NULL")
    elif origin:
        where.append(f"{alias}.origin_kind = :origin")
        params["origin"] = origin
    if model.strip():
        where.append(f"{alias}.model_name ILIKE :model")
        params["model"] = f"%{model.strip()}%"
    if q.strip():
        where.append(f"({alias}.first_human_message ILIKE :q OR {alias}.last_ai_message ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    return " AND ".join(where), params


BAD_STATUSES = "('error', 'timeout', 'interrupted')"

ERROR_GROUPS = f"""
SELECT coalesce(e.error_type, nullif(split_part(r.error, ':', 1), ''), 'unknown') AS error_type,
       count(*) AS runs,
       count(DISTINCT r.user_id) AS users,
       max(r.created_at) AS last_seen,
       min(r.run_id) AS sample_run
FROM runs r
LEFT JOIN LATERAL (
    SELECT event_metadata::jsonb ->> 'error_type' AS error_type
    FROM run_events
    WHERE thread_id = r.thread_id AND run_id = r.run_id
      AND event_type IN ('run.error', 'llm.error')
    ORDER BY seq
    LIMIT 1
) e ON true
WHERE __WHERE__ AND r.status IN {BAD_STATUSES}
GROUP BY 1
ORDER BY 2 DESC
"""

ERROR_RECENT = f"""
SELECT r.run_id, r.thread_id, r.user_id, r.status, r.model_name, r.error,
       r.created_at, r.updated_at, r.first_human_message,
       e.error_type
FROM runs r
LEFT JOIN LATERAL (
    SELECT event_metadata::jsonb ->> 'error_type' AS error_type
    FROM run_events
    WHERE thread_id = r.thread_id AND run_id = r.run_id
      AND event_type IN ('run.error', 'llm.error')
    ORDER BY seq
    LIMIT 1
) e ON true
WHERE __WHERE__ AND r.status IN {BAD_STATUSES}
ORDER BY r.created_at DESC
LIMIT 100
"""

ERROR_DAILY = f"""
SELECT r.created_at::date AS day,
       count(*) AS total,
       count(*) FILTER (WHERE r.status IN {BAD_STATUSES}) AS bad
FROM runs r
WHERE __WHERE__
GROUP BY 1
ORDER BY 1
"""

OUTLIER_STATS = """
SELECT max(r.total_tokens) AS max_tokens,
       max(extract(epoch FROM (r.updated_at - r.created_at))) AS max_seconds,
       max(r.llm_call_count) AS max_calls,
       count(*) FILTER (
         WHERE (r.status IN ('pending', 'running') AND r.updated_at < now() - interval '30 minutes')
            OR (r.status NOT IN ('pending', 'running') AND r.updated_at - r.created_at > interval '6 hours')
       ) AS stale
FROM runs r
WHERE __WHERE__
"""

OUTLIER_SELECT = """
SELECT r.run_id, r.thread_id, r.user_id, r.status, r.model_name,
       r.total_tokens, r.llm_call_count, r.created_at, r.updated_at,
       r.first_human_message, u.email
FROM runs r
LEFT JOIN users u ON u.id = r.user_id
WHERE __WHERE__
ORDER BY {order}
LIMIT 20
"""

OUTLIER_TOKENS = OUTLIER_SELECT.format(order="r.total_tokens DESC")
OUTLIER_SECONDS = OUTLIER_SELECT.format(order="(r.updated_at - r.created_at) DESC")
OUTLIER_CALLS = OUTLIER_SELECT.format(order="r.llm_call_count DESC")

STALE_RUNS = """
SELECT r.run_id, r.thread_id, r.user_id, r.status, r.model_name,
       r.total_tokens, r.llm_call_count, r.created_at, r.updated_at,
       r.first_human_message, u.email
FROM runs r
LEFT JOIN users u ON u.id = r.user_id
WHERE __WHERE__
  AND (
    (r.status IN ('pending', 'running') AND r.updated_at < now() - interval '30 minutes')
    OR (r.status NOT IN ('pending', 'running') AND r.updated_at - r.created_at > interval '6 hours')
  )
ORDER BY r.updated_at DESC
LIMIT 20
"""

TREND_DAILY = f"""
SELECT r.created_at::date AS day,
       count(*) AS runs,
       count(*) FILTER (WHERE r.status = 'success') AS ok,
       count(*) FILTER (WHERE r.status IN {BAD_STATUSES}) AS bad,
       coalesce(sum(r.total_tokens), 0) AS tokens,
       count(DISTINCT r.user_id) AS users
FROM runs r
WHERE __WHERE__
GROUP BY 1
ORDER BY 1
"""

TREND_PERCENTILES = """
SELECT r.created_at::date AS day,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (r.updated_at - r.created_at))) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (r.updated_at - r.created_at))) AS p95
FROM runs r
WHERE __WHERE__ AND r.status = 'success'
GROUP BY 1
ORDER BY 1
"""

TREND_MODELS = """
SELECT coalesce(r.model_name, '-') AS model, count(*) AS runs, coalesce(sum(r.total_tokens), 0) AS tokens
FROM runs r
WHERE __WHERE__
GROUP BY 1
ORDER BY 2 DESC
"""

TREND_ORIGINS = """
SELECT coalesce(r.origin_kind, 'interactive') AS origin, count(*) AS runs
FROM runs r
WHERE __WHERE__
GROUP BY 1
ORDER BY 2 DESC
"""

SKILL_USED_CTE = """
WITH used AS (
  SELECT e.run_id, e.thread_id, e.user_id, e.created_at, s
  FROM (
    SELECT run_id, thread_id, user_id, created_at, content::jsonb AS j
    FROM run_events
    WHERE event_type = 'llm.ai.response'
      AND created_at >= now() - make_interval(days => CAST(:days AS int))
      AND content LIKE '%"skill_usages"%'
      AND pg_input_is_valid(content, 'jsonb')
  ) e
  CROSS JOIN LATERAL jsonb_array_elements(e.j -> 'additional_kwargs' -> 'skill_usages') s
)
"""

SKILLS = (
    SKILL_USED_CTE
    + """
SELECT s ->> 'name' AS skill,
       max(s ->> 'category') AS category,
       string_agg(DISTINCT s ->> 'activation', ',') AS activation,
       count(DISTINCT run_id) AS runs,
       max(created_at) AS last_used
FROM used
GROUP BY 1
ORDER BY 4 DESC
"""
)

SKILL_TOTAL = (
    SKILL_USED_CTE
    + """
SELECT count(DISTINCT run_id) AS runs, count(DISTINCT s ->> 'name') AS skills
FROM used
"""
)

SKILL_REFS = """
SELECT s AS skill, count(DISTINCT run_id) AS runs
FROM (
  SELECT run_id, content::jsonb AS j
  FROM run_events
  WHERE event_type = 'llm.human.input'
    AND created_at >= now() - make_interval(days => CAST(:days AS int))
    AND content LIKE '%"skill_references"%'
    AND pg_input_is_valid(content, 'jsonb')
) e
CROSS JOIN LATERAL jsonb_array_elements_text(e.j -> 'additional_kwargs' -> 'skill_references') s
GROUP BY 1
"""

SKILL_ACTIVATIONS = """
SELECT content::jsonb -> 'changes' ->> 'skill_name' AS skill, count(DISTINCT run_id) AS runs
FROM run_events
WHERE event_type = 'middleware:skill_activation'
  AND created_at >= now() - make_interval(days => CAST(:days AS int))
GROUP BY 1
"""

SKILL_DESCRIBES = """
SELECT count(*) AS n
FROM run_events
WHERE event_type = 'llm.tool.result'
  AND content LIKE '%describe_skill%'
  AND created_at >= now() - make_interval(days => CAST(:days AS int))
"""

SKILL_DETAIL = (
    SKILL_USED_CTE
    + """
SELECT run_id, thread_id, user_id, created_at,
       max(s ->> 'category') AS category,
       string_agg(DISTINCT s ->> 'activation', ',') AS activation
FROM used
WHERE s ->> 'name' = :skill
GROUP BY 1, 2, 3, 4
ORDER BY created_at DESC
LIMIT 100
"""
)
