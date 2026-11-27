# Operations console (`deploy/ops/`)

A standalone, read-only web page for looking at users, their runs and their
conversations. It is deliberately separate from the application:

- it does **not** run inside the Gateway, import `deerflow`/`app`, or share a
  connection pool with the agent runtime;
- it only issues `SELECT` statements; the database role is read-only and
  `default_transaction_read_only` is on;
- it uses its own compose file, so starting or stopping it never touches the
  Gateway, frontend, Postgres or Redis;
- it has no authentication. Bind it to loopback and reach it through an SSH
  tunnel, or put it behind your own access layer.

It answers: *who used the system, what did they ask, what did the assistant
answer, how many tokens did it cost, and which runs failed.*

## What it reads

| Table | Used for |
| --- | --- |
| `users` | owner email, role, disabled flag |
| `threads_meta` | conversation title and owner |
| `runs` | status, model, tokens, timing, `first_human_message`, `last_ai_message`, error |
| `run_events` | full message timeline for one conversation (only when you open it) |
| MySQL `st_mgr_user` (optional) | user `code`, matched against the PG email prefix |

## User code mapping (optional)

Set the `OPS_MYSQL_*` variables and the console shows the MySQL `code` instead
of the raw email. The match is:

```
LOWER(st_mgr_user.code) == LOWER(prefix of users.email before "@")
```

Only emails on `OPS_MAP_EMAIL_DOMAIN` (default `users.deerflow.internal`) are
eligible. The prefix is matched against MySQL `code` first, then against the
digits of `mobile`, because an internal account may log in with either:

- `sh02311@users.deerflow.internal` → `code = SH02311` → shows `sh02311`
- `18939869352@users.deerflow.internal` → `mobile = 18939869352` → shows
  the code of that row (`sh02311`)

The displayed label is always the lowercased code. Personal accounts
(`@qq.com`, `@163.com`, ...) are never mapped and keep their email, even if
their prefix happens to look like a code or mobile. If MySQL is unconfigured or unreachable, every user falls back
to email and the page still works; the code set is cached for
`OPS_CODE_CACHE_SECONDS` (default 300).

The MySQL account should be read-only. Only `SELECT` on `a_sh_mgr.st_mgr_user`
is issued; table and column names come from validated identifiers, never from
request input.

The run list touches `run_events` only for the optional tool summary. The
conversation page reads at most 1,000 message rows for one thread; the run
detail page reads one run's events through `(thread_id, run_id)`.

## Setup

1. Create the read-only role. Run [`sql/readonly_role.sql`](sql/readonly_role.sql)
   as a superuser, after changing the database name, password and schema.
   The CECE deployments use `postgres_schema: deerflow`, so the tables are
   `deerflow.runs`, `deerflow.users`, etc., not `public.*`.

   ```bash
   psql "postgresql://cece:<superuser-password>@172.25.18.172:15432/<database>"
   # inside psql: SELECT current_database(); SHOW search_path;
   ```

2. Create the environment file:

   ```bash
   cd deploy/ops
   cp .env.example .env
   # edit OPS_DATABASE_URL, OPS_DB_SCHEMA and DEER_FLOW_NETWORK
   ```

   Use the dedicated `ops_readonly` password, never the superuser password.
   Find the network name with `docker network ls | grep cece`.

   - **Same Docker host (recommended):** join the application network and
     address Postgres by container name:
     `postgresql+asyncpg://ops_readonly:<pw>@cece-harness-dev172-postgres:5432/deerflow`
     with `DEER_FLOW_NETWORK=cece-harness-dev172-net`.
   - **Outside the Docker network:** use the published port
     (`172.25.18.172:15432`) and make sure the firewall only allows your host.

3. Build and start:

   ```bash
   docker compose -f docker-compose.ops.yaml up -d --build
   ```

   The published address is `${OPS_BIND_HOST:-127.0.0.1}:${OPS_PORT:-8099}`.
   Keep `OPS_BIND_HOST=127.0.0.1` and use a tunnel, or set a LAN IP and restrict
   the firewall.

4. Open it:

   ```bash
   # loopback bind:
   ssh -L 8099:127.0.0.1:8099 <user>@<host>
   # then: http://127.0.0.1:8099

   # LAN bind (OPS_BIND_HOST=192.168.x.y):
   # http://192.168.x.y:8099
   ```

   `GET /healthz` returns `ok` when the database is reachable.

## Pages

- `/` — recent runs (default 7 days), with user/status/origin/model/keyword
  filters, tool summary, error type, duration, token split and trace.
- `/users` — every user, ranked by runs in the window, with tokens and failures.
- `/errors` — failure rate, error types (from `run.error` / `llm.error`),
  daily failures and the most recent failed runs.
- `/outliers` — largest runs by tokens, duration and model calls, plus stale
  `pending`/`running` runs and terminal runs longer than 6 hours.
- `/trends` — daily runs (success/failure), tokens, active users, p50/p95
  duration, by model and origin.
- `/skills` — skills actually loaded per run (`skill_usages`), plus explicit
  `@` references and middleware activations; `/skills/{name}` shows one skill.
- `/runs/{run_id}` — one run's error, token split, loaded skills and event
  timeline.
- `/threads/{thread_id}` — the message timeline: user input, assistant answers,
  and collapsed tool results.

Skill counts use three different signals and should not be mixed:

| Signal | Source | Meaning |
| --- | --- | --- |
| Loaded | `llm.ai.response` → `additional_kwargs.skill_usages` | The skill content was actually read in that run |
| Explicit reference | `llm.human.input` → `additional_kwargs.skill_references` | The user selected the skill with `@` |
| Activation | `middleware:skill_activation` | The middleware activated a skill |
| Discovery | `llm.tool.result` containing `describe_skill` | The model only looked up the catalog; not usage |

Loaded counts deduplicate repeated reads inside one run and exclude subagent
loads.

## Impact on production

Measured on the 224 database (2026-11-26; 260 runs, ~9,000 events):

| Query | Server time | Plan |
| --- | ---: | --- |
| Run list (200 rows) | 2.5 ms | sequential scan of `runs` + sort |
| Error types | 5.7 ms | scan of `run_events`, 37 matches |
| Thread page (1,000 messages) | 0.6 ms | bitmap index on `(thread_id, category, seq)` |
| Outliers / trends | 0.3–0.5 ms | `runs` only |
| Tool aggregate | ~725 ms | on by default; scans `run_events` and parses JSON. Use `details=0` to hide |
| Skill aggregate | ~497 ms | scans `run_events` for `skill_usages`; cached 60 s |
| Per-user tool events | ~223 ms | `user_id` index + JSON parse |

| Concern | Measure |
| --- | --- |
| Query load | Only when a page is opened; tool/skill aggregates are cached 60 s and can be hidden |
| Slow queries | `statement_timeout=5s` on the connection |
| Writes | Impossible: read-only role + `default_transaction_read_only` |
| Locks | Plain `SELECT`; no `FOR UPDATE`, no advisory locks, no blocking of event writes |
| Connections | One idle session; 27 of 100 `max_connections` in use |
| Process isolation | Separate container, `mem_limit: 512m`, `cpus: 1`, `read_only` rootfs |
| Blast radius | `docker compose -f docker-compose.ops.yaml down` ends it completely |

Two honest caveats:

- `runs` has no index on `created_at`, so the list query is a sequential scan.
  It is milliseconds at 226 rows but grows with the table. If it becomes slow,
  add an index during a quiet window (this is a production schema change):
  `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_runs_created_at ON deerflow.runs (created_at DESC);`
- The tool aggregate runs by default (about 0.4–0.8 s of database time). Use the
  "隐藏" link or `?details=0` to skip it. If it becomes slow as the event table
  grows, index `(run_id, event_type)` or keep it hidden by default.

If the keyword search becomes slow on a large `runs` table, add a
trigram index during a quiet window:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_runs_first_human_trgm
  ON runs USING gin (first_human_message gin_trgm_ops);
```

## Notes and limits

- **No login.** That is intentional for a single-operator tool. `OPS_BIND_HOST`
  controls the published interface: keep `127.0.0.1` and use an SSH tunnel, or
  set a LAN IP and restrict the firewall to trusted sources.
- **Data is live**, not a snapshot: it reads the application database directly.
  A read replica is unnecessary at this query volume; add one only if the page
  becomes multi-user or starts running heavy aggregations.
- **Tool output is truncated** to 4,000 characters per message in the page.
- The page is Chinese-only and uses the server timezone from `OPS_TZ`.
- If the deployment sets `database.postgres_schema`, set `OPS_DB_SCHEMA` to the
  same value so the role's `search_path` matches.
- The event-table aggregates are the only queries that grow with history. They
  have a 5 s statement timeout, a 60 s cache and a time window; if they become
  slow, hide the tool column or add the indexes listed above.

## Tests

The tests do not need a database:

```bash
cd backend
uv run --no-sync python -m pytest ../deploy/ops/tests -q
```