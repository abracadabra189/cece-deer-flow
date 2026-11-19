# Skills (`deerflow/skills/`)

Loads `SKILL.md` packages, projects them into the sandbox, scans and reviews them,
and owns install, export, history and the mutation (skill evolution) host.
Sub-packages: `skillscan/` (offline deterministic scanner), `review/` (read-only
review core and CLI), `mutations/` (evolution host). Related docs:
[skill evolution host](../../../../../docs/skill-evolution-host.md),
[export API](../../../../docs/API.md#export-a-custom-skill).

## Verify

```bash
cd backend
python -m pytest tests -q -k "skill"
make test-blocking-io
```

## Where skills live

Public skills live in `skills/public/`; custom skills and managed integration packs
live under `{DEER_FLOW_HOME}` per user and per provider, while their credentials
and enabled state stay per user.

## Loading and caches

- **A directory with `SKILL.md` is a package boundary.** The loader recurses
  through provider and namespace directories and stops at the first `SKILL.md`. A
  nested fixture must not become a catalog entry or shadow a public skill.
- **`frontmatter.py` is the only frontmatter parser.** Runtime loading,
  installation validation and review all use it, so the three cannot disagree on
  what a skill declares.
- **Storage does not cache the catalog.** Only the prompt-layer caches in
  `agents/lead_agent/prompt.py` differ between Gateway processes sharing a home
  volume; every mutation route resets them through the shared reset.
- **`allowed-tools` is compatibility metadata** for other agent frameworks:
  parsed, validated, exported. It never filters tools, refuses calls or narrows a
  subagent; authority lives in the Agent configuration.
- **Enrolled owners need the mutation runtime.** A standalone SDK or storage
  process has no publication runtime, so it refuses reads and writes for an owner
  that is enrolled in skill evolution. Check enrollment on each access; a cached
  negative answer goes stale.

## Files on disk

- **Publish with a same-directory temporary file and a replace**, then make the
  result readable by the sandbox. Failed writes clean up through
  `utils.atomic_write.cleanup_failed_atomic_write`.
- **Projection readers and mutation writers share the owner lock.** Export also
  captures its bytes under that lock and re-checks them. A read-only export does
  not rebuild projections.
- **A skill name is a directory name on every host.** Creation and archive install
  reject Windows reserved device names on all platforms. Reads and deletes stay
  permissive, so that skills stored by an older release can still be removed.
- **History is JSONL split on LF only**; Unicode separators in a saved field are
  data.
- **Export is not a secret audit**: raw saved files, relative paths, generic
  errors; limits are reported, not applied by silent truncation.

## Scanning

- **SkillScan is deterministic and offline.** It runs before the model-based
  scanner on `.skill` archives and on agent-managed skill writes. Evidence in a
  finding is redacted.
- **A rule change needs both directions tested**: triggering cases and look-alike
  quiet cases (a real API key in a Bearer header versus a placeholder). Keep regex
  alternatives disjoint so long non-matching input cannot backtrack quadratically.
- **The review core is read-only.** It does not import `app.*` and does not execute
  the scripts of the skill it reviews.

### Auto skill synthesis (`skills/auto/`)

`auto_skill.enabled` distils each **completed** run's whole trajectory into a
reusable skill, off the run's critical path (the producer enqueues in
`after_agent`; a debounced daemon worker drains). Full contract, naming and gates:
[AUTO_SKILL.md](../../../../docs/AUTO_SKILL.md). Traps:

- Writes settle as one `await_drained` unit through the *same* gates as
  `skill_manage`; repeats create `v{n+1}`, and retention prunes only
  `metadata.author: auto-skill` candidates, so an operator's skill survives.
- A declared `update` is verified, not trusted (`decision.py`): data-only reasons
  degrade to `no_change`. Bodies are abstract (`abstraction.py`): declared entities
  may appear only in `## 示例`, else one repair attempt then redaction.
- The batch's `asyncio.run` closes its loop on return, so the batch owns its model
  HTTP client (`utils.oneshot_llm.new_isolated_http_client()`, passed as
  `http_async_client` into every model call, closed before the loop dies):
  langchain-openai caches its default client per process on connection parameters
  alone, and dead-loop connections pooled there resurface as `RuntimeError: Event
  loop is closed` on unrelated chats. Tests: `tests/test_auto_skill_http_isolation.py`;
  the e2e suite stubs only the model and asserts discoverability.

## Request-scoped secrets

A skill declares `required-secrets` in its frontmatter. The caller sends the values
in the run request's `context.secrets`, and `bash` receives them as environment
variables for the activation turn only.

- **The value stays out of every observable surface.** It is not in a message, a
  tool argument, the command string, a trace, a checkpoint or the audit journal.
  Check all of them when you touch this path.
- **Nothing is stored on the server.** The caller supplies the secrets on each
  request. Subagents do not inherit the injection set.
- **The injection set is recomputed on every model call** and replaces the previous
  one, so a secret cannot outlive the skill activation that asked for it.
- **Hiding a legacy field in an API response does not delete it.** Values that
  older releases stored in databases, run events or backups remain there. A
  deployment that used the legacy carriers has to rotate the credential.

## Evolution host

- A proposal has one shared, shielded check. A cancelled waiter does not cancel
  the scan. A cancelled or timed-out scan leaves no cached verdict and still counts
  toward the hourly quota.
- Lease cleanup is fenced by token, so it cannot erase the lease of a replacement
  worker.
- Recovery of one operation reports an unresolved owner barrier as `NEEDS_REPAIR`.
  Only the host-wide sweep skips it to continue with other owners.

