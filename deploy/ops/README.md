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
`OPS_CODE_CACHE_SECONDS` (default 60).

The MySQL account should be read-only. Only `SELECT` on `a_sh_mgr.st_mgr_user`
is issued; table and column names come from validated identifiers, never from
request input.

The run list does not touch `run_events`, so the common page is cheap. The
conversation page reads at most 1,000 message rows for one thread.

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

   The container listens on `127.0.0.1:8099` only.

4. Open it through a tunnel:

   ```bash
   ssh -L 8099:127.0.0.1:8099 <user>@<host>
   # then: http://127.0.0.1:8099
   ```

   `GET /healthz` returns `ok` when the database is reachable.

## Pages

- `/` — recent runs (default 7 days), with user/status/keyword filters and
  headline counters.
- `/users` — every user, ranked by runs in the window, with tokens and failures.
- `/threads/{thread_id}` — the message timeline: user input, assistant answers,
  and collapsed tool results.

## Impact on production

| Concern | Measure |
| --- | --- |
| Query load | Only when a page is opened; each page runs 2–3 indexed/limited queries |
| Slow queries | `statement_timeout=5s` on the connection |
| Writes | Impossible: read-only role + `default_transaction_read_only` |
| Process isolation | Separate container, `mem_limit: 512m`, `cpus: 1`, `read_only` rootfs |
| Blast radius | `docker compose -f docker-compose.ops.yaml down` ends it completely |

The run list filters on `created_at` and reads at most 200 rows; it never scans
`run_events`. If the keyword search becomes slow on a large `runs` table, add a
trigram index during a quiet window:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_runs_first_human_trgm
  ON runs USING gin (first_human_message gin_trgm_ops);
```

## Notes and limits

- **No login.** That is intentional for a single-operator tool. Keep the port
  bound to `127.0.0.1`; do not publish it on a LAN interface.
- **Data is live**, not a snapshot: it reads the application database directly.
  A read replica is unnecessary at this query volume; add one only if the page
  becomes multi-user or starts running heavy aggregations.
- **Tool output is truncated** to 4,000 characters per message in the page.
- The page is Chinese-only and uses the server timezone from `OPS_TZ`.
- If the deployment sets `database.postgres_schema`, set `OPS_DB_SCHEMA` to the
  same value so the role's `search_path` matches.