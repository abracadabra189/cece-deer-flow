# Router contracts

Artifact range validators and bytes come from one opened file. POSIX streams the
descriptor; Windows copies only the selected response bytes to a private temporary
file and closes the public handle before sending headers. Preserve the ZIP
single-link checks and drain preparation before cancellation can release resources.

Trash listing resolves the live retention config off-loop before its best-effort
sweep; config failures skip cleanup and preserve the listing — never substitute a
default policy for an unreadable one.

HTTP creation holds `goal_thread_lock` from the idempotency lookup through the
initial checkpoint write. Same-id creates return the existing row, including in
memory mode; retain the native store's overwrite contract and SQL duplicate-insert
recovery across workers. Tests: `test_thread_create_idempotency.py`.

`GET /api/plugins/diagnostics` is `require_admin_user` before reading the canonical
snapshot; return bounded identifiers, levels and fixed summaries, never clear the
sink, never expand PAT permissions.

Branch metadata inherits valid `assistant_id` values verbatim and clears invalid
legacy values to null in the new row, leaving the source record unchanged.

Console usage attributes legacy rows without a per-model map to `model_name`;
counters that do not coerce to integers contribute zero and unusable rows fall back
to run-level totals instead of aborting. Coverage: `tests/test_console_router.py`.

Scheduled tasks: shared update validation preserves an unchanged future `once`
instant inside `scheduler.min_once_delay_seconds`; admission rejects nonexistent
naive `run_at`/`end_at` wall times through the shared datetime resolver, but keeps
that check out of runtime `next_run_at` so legacy tasks retain their accepted
instant and ambiguous naive times keep their fold.

Custom Agent packages are versioned definition-only JSON: export projects the
caller's portable fields and SOUL, excluding installation bindings, memory,
conversations and credentials; import is create-only and owner-scoped, colliding
with 409. Creation and import share `_persist_new_agent` under `run_drained_write`.
Update guards apply legacy shared-file checks only for `FileAgentStore`; DB rollback
files cannot veto SQL updates. `PUT` clears an inherited knowledge default when
changed groups remove knowledge access; explicit scope/null updates still win.

`GET /api/skills`, `/api/skills/custom` and `/api/skills/{name}` serve every
signed-in user, so unexpected-failure 500s return a fixed detail; load errors (e.g.
a malformed `extensions_config.json`) carry host paths and stay in the log. The
same rule covers upload, upload-delete and shelf-attach 500s: name the file, not
the cause. Operation lists return `next_cursor: null` unless a page follows.

`GET /api/agent-tool-groups` projects only configured group names; never expose
tool provider paths, credentials or raw tool configuration.

MCP mutation 500s and the scheduled-task `invalid_assistant` 422 use fixed text;
log exceptions server-side (they can carry host paths). Committed reconciliation
failures are logged once by `fail_mcp_reconciliation` with only the exception type;
`_run_drained_mcp_apply` passes `_McpCommittedReconciliationError` to
`run_drained_write` as expected, still drains retired-pool cleanup outside the
config locks, and reports the fixed-detail 500.

Custom-skill edit, delete and rollback hold the owning root's process mutex and
`.custom.mutation.lock` sidecar across predecessor read, storage mutation and
history append, so peers sharing the root keep history ordering; acquire and
release both off-loop in the drained worker. Archive upload copies report the
original size-limit or read error when temporary cleanup or its warning fails and
return the uploaded bytes unchanged on success; the route's `finally` discards the
archive before closing the multipart form, so cleanup failures cannot replace the
install outcome. Coverage: `tests/test_skill_archive_upload_cleanup.py`.

Plugin actions stamp `ActionContext.interaction=session` only from authenticated
session provenance; never accept it from payloads or propagate it to model tools.

State updates synchronize titles into thread metadata for the root checkpoint
namespace only; nonroot writes preserve title, branch sequence and activity
timestamp. Coverage: `tests/test_threads_router.py`.

Unauthenticated auth routes (`/register`, `/setup-status`, `/providers`,
`/oauth/{provider}`, `/callback/{provider}`, the `/login/local` throttle and the
external-user gates) read `get_app_config()` through `asyncio.to_thread`: each read
stats and hashes the config files. Coverage:
`tests/blocking_io/test_auth_router_config_reads.py`.

External user-system provisioning (`/api/v1/auth/external`) is public in
`AuthMiddleware` while self-authenticating on its shared `api_key`, like the signed
webhooks. Its ticket is single-use through an atomic DB claim and can never replay
as a session. Contract: `backend/docs/API.md#external-user-provisioning`; trust
boundary: `backend/docs/AUTH_DESIGN.md`. Tests: `test_external_user_auth.py`.

Managed-model `/discover` and `/import` require admin before reading credentials or
going outbound. Discovery is read-only and bounded (20s, 2 MiB, 2,000 IDs/20 pages),
never follows redirects, and rejects compressed bodies before decoding. Import
probes each new profile, saves through the drained writer, deduplicates retries
atomically without touching disabled profiles, and reuses a saved key only with
matching connection and revision re-checked under the write lock (409 on change).

Agent-scoped memory routes validate `agent_name` with `AGENT_NAME_PATTERN` and
require `supports_agent_scoped_management` (else 501). The scope-creating routes
(`POST /memory/facts`, `POST /memory/import`) also reject Windows reserved device
names via `windows_incompatible_segment()`: the scope is a host directory, so the
character class alone once answered 500 with `FileNotFoundError`. Keep reads and
deletes permissive so reserved-name scopes from older releases stay exportable.
Tests: `test_memory_router.py`.
