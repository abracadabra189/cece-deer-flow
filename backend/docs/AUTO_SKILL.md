# Auto Skill — Post-Run Skill Synthesis

`auto_skill.enabled` lets DeerFlow learn a reusable skill from each **completed**
run, so the next similar query matches it instead of re-deriving the same
data-fetching and reasoning path from scratch.

This complements `skill_evolution` rather than replacing it:

| | `skill_evolution` | `auto_skill` |
|---|---|---|
| Who decides | the agent, mid-run, via the `skill_manage` tool | the platform, after the answer is delivered |
| Turn cost | spends an agent turn | spends none |
| Sees | what the agent chooses to record | the whole trajectory, including tool results |
| Scope of the result | the writing user's custom skills | **global — every user** |

Both write through the **same** validation and security-scan pipeline, so
auto-generated content is never trusted more than agent-written content.

Code: `packages/harness/deerflow/skills/auto/` plus the producer hook
`agents/middlewares/auto_skill_middleware.py`. Config:
`config/auto_skill_config.py` (`auto_skill:` in `config.yaml`).

---

## Flow

```
run completes, answer already streamed
  └─ AutoSkillMiddleware.after_agent            (lead chain only)
       ├─ extract_run_trajectory(state)         in-memory, bounded, never raises
       ├─ gates: query? final answer? min_tool_calls?
       └─ AutoSkillQueue.submit(...)            O(1), returns immediately
            └─ daemon Timer fires after debounce_seconds
                 └─ asyncio.run(_process_batch)  fresh loop per batch
                      └─ synthesize_skill(...)
                           ├─ resolve the auto-skills this run actually hit
                           ├─ evidence = trajectory + hit skills + tool diff + scenario index
                           ├─ run_oneshot_llm → decision + structured JSON
                           │     ├─ no_change → stop (nothing is written)
                           │     └─ create / update → continue
                           ├─ scenario_slug → stable visible name
                           ├─ verify the update claim (reasons + tool evidence)
                           │     └─ unsubstantiated → stop, as no_change
                           ├─ abstraction gate: entity leak → repair → redact
                           ├─ render SKILL.md
                           ├─ validate + enforce_static_scan + scan_skill_content
                           ├─ store.write_skill  (lock → stage → backup old → rename)
                           ├─ global prompt-cache invalidation (no user_id)
                           ├─ prune backups beyond max_versions
                           └─ sweep legacy per-user packages for this scenario
```

---

## Requirement 1 — global sharing

A skill learned from user A's run must be matchable by user B, so it cannot live
in `users/{uid}/skills/custom/`. It is published under the **global integrations
root**:

```
{DEER_FLOW_HOME}/integrations/skills/auto-skill/{name}/SKILL.md
```

That location is the only one satisfying all three constraints at once:

| Candidate | Always scanned by every user? | Writable at runtime? | Verdict |
|---|---|---|---|
| `skills/public/` | yes | **no** — the production compose mounts `../skills` read-only | rejected |
| global `skills/custom/` (LEGACY) | **no** — shadow-mount hides it from any user who owns a custom skill | yes | rejected |
| `users/{uid}/skills/custom/` | only that user | yes | rejected (per-user) |
| `integrations/skills/{provider}/` | **yes** — step 2 of `_iter_skill_files`, unconditional | yes (under `DEER_FLOW_HOME`) | **used** |

Enabled state also works out: `ExtensionsConfig.is_skill_enabled` returns true
for the `integrations` category when no entry exists, and
`UserScopedSkillStorage.get_skill_enabled_state` defaults to true, so a newly
published skill is **on for every user with no manual toggle**.

**Accepted trade-off.** Packages under the integrations root surface in the UI as
read-only managed integration skills — the same tier as the official Lark pack —
so `ensure_custom_skill_is_editable` refuses edits and deletes. The escape hatch
is the platform's existing shadowing rule: CUSTOM is scanned *after* INTEGRATION
and `load_skills` dedupes by name with the later category winning, so any user can
create a same-named custom skill to get a private variant without affecting
anyone else.

**Sandbox projection needs no explicit rebuild.** `_source_signature(storage,
"user")` digests the integrations tree's metadata, and `ensure_skill_projections`
runs on every sandbox acquire, so each user's view repairs itself lazily. Atomic
rename guarantees a new inode, which is what makes that detection reliable — an
in-place edit preserving inode+size+mtime would not be seen (the documented
trade-off of metadata-only digesting).

---

## Requirement 2 — latest-only visibility with a recoverable history

The visible name is **stable**: `{name_prefix}-{scenario-slug}`, with no version
suffix. The version lives in frontmatter `metadata.version` and in the backup
directory name:

```
visible : {base}/integrations/skills/auto-skill/auto-pevc-funding/SKILL.md     (v3)
backups : {base}/auto-skill-backup/auto-pevc-funding/v1/SKILL.md
                                   /v2/SKILL.md
```

Consequences:

- **exactly one package per scenario is ever discoverable** — "users only see the
  latest version" holds structurally, not by pruning;
- an update never churns the name, so skill matching, `ThreadState.skill_context`
  references and anything a user bookmarked keep working;
- the backup root sits outside every scanned root, so backups can never be
  mistaken for skills;
- `restore_backup(name, version)` rolls forward again — the restore is itself a
  version bump, so the version being rolled off is preserved too and an operator
  can undo the undo.

### The update decision

When the run actually loaded an existing auto-skill, that skill's current content
is handed to the model alongside the trajectory, and the model returns an
explicit `decision`:

| decision | meaning | effect |
|---|---|---|
| `no_change` | the run stayed inside the skill's definition — only its subject, values or examples differ | **nothing is written** — no version churn, no scan cost |
| `update` | the run went **beyond** the skill's definition (see the verified reasons below) | old package → backup store, improved package published |
| `create` | no existing skill covers the scenario | first publication |

An unknown or absent `decision` degrades to `create`; `no_change` short-circuits
before the security scans, so a no-op run costs one model call and nothing else.
A `create` decision aimed at a name that already exists is recorded as `update`,
so the audit trail describes what actually happened.

### The update is verified, not trusted

An update rewrites a package **every user shares**, so a declared `update` must
carry evidence. `skills/auto/decision.py` owns the contract:

| `update_reasons` value | counts as substantive | note |
|---|---|---|
| `new_tool` | yes | **evidence-checked** — dropped when the platform's own tool diff finds no tool outside the skill's text |
| `new_flow` | yes | different data-fetch order or reasoning path |
| `answer_format` | yes | the answer structure was improved |
| `new_dimension` | yes | the user asked for, or the run added, an answer dimension |
| `correction` | yes | a wrong command, parameter or data definition was fixed |
| `fallback` | yes | a new failure fallback / alternative path |
| `examples_only`, `data_values`, `wording` | **no** | this run's data, never a reason to rewrite |
| anything else | **no** | unknown tokens are dropped, not trusted |

`verify_update()` keeps the update only when at least one substantive reason
survives; otherwise the decision degrades to `no_change`, nothing is written and
the log says why. A declared `update` with **no** reasons at all also degrades —
the vocabulary is the contract. The one exception is a `create` that the store
reconciles to an update because the scenario already exists: the create vocabulary
carries no reasons, so absence is not a failed check (`strict=False`), but reasons
that *are* declared still get verified.

The tool diff is computed once and used twice: it is rendered into the prompt as
`## 平台确定性核对：工具差异` (so the model's `new_tool` claim and the verifier
agree), and it is the evidence `verify_update` checks against. The comparison
covers both the skills the run loaded and the target package it is about to
rewrite — a run can reach an existing scenario through the scenario index without
ever loading it.

Dropped reasons and downgrades are logged at INFO; `SynthesizedSkill.update_reasons`
carries the surviving ones for the audit trail.

### The scenario index

`skill_context` is frequently empty: the model often goes straight to the tools
without reading the `SKILL.md`, so a run can belong to an existing scenario while
never "hitting" its skill. Relying on `skill_context` alone would let the
synthesizer mint a near-duplicate package under a different slug.

`_render_scenario_index()` therefore lists every existing global auto-skill
(`name`, version, bounded description) in the prompt, with an explicit instruction
to reuse the matching `scenario_slug`. That makes the stable name the join key:
reusing the slug resolves to the same package, which turns the write into an
update. The index is bounded (`_INDEX_MAX_ENTRIES`, `_INDEX_DESCRIPTION_BUDGET`)
and omitted entirely when nothing has been learned yet.

Verified live: a run whose `skill_context` was empty but which added
`get_enterprise_shareholders` to an existing scenario still produced
`update v2` with `v1` archived, rather than a duplicate skill.

### Unparseable model output

A reasoning model occasionally answers in prose or emits a truncated object. One
retry is made with a stricter instruction appended, and both failures log a
bounded snippet of the raw response (`_RAW_DIAGNOSTIC_BUDGET`) — without it this
failure mode is undiagnosable in production. Two failures drop the trajectory.

---

## Abstraction: a skill describes a class of questions

A generated skill must describe a **class** of questions. If its body hard-codes
one company, the next run about another company either fails to match it or, worse,
matches it and follows a procedure written for somebody else. So every surface
except the examples section must stay abstract:

| surface | concrete entities allowed |
|---|---|
| `scenario`, `description` | no — these drive matching, so an entity narrows the skill to one subject |
| `when_to_use`, `data_fetching`, `reasoning`, `answer_format`, `caveats` | no — method and path only |
| `examples` | **yes** — this is where the run's subject, arguments and result skeleton live |

The model declares the run's entities (`entities`) and the platform checks them
against the abstract surfaces (`skills/auto/abstraction.py`). On a leak:

1. **one repair attempt** — the model is re-prompted with the leaked entity list
   and asked to abstract them, keeping its decision and slug; content fields are
   adopted from the retry, decision fields are not (a second opinion must not
   rename the package mid-flight);
2. **deterministic redaction** — a repair that fails, raises, returns unparseable
   output or still leaks is replaced by `redact_entities()`, which substitutes
   `ENTITY_PLACEHOLDER` (`【实体】`), longest entity first so overlapping matches
   cannot leave fragments, collapsing adjacent placeholders.

The examples section is never redacted. `SynthesizedSkill.redacted_entities`
records what the platform had to remove, and the rewrite is logged at WARNING: a
redacted skill is published, but a model that keeps leaking is worth knowing about.
Entities are bounded (2–64 chars, at most 40) so a model that declares the whole
answer as "entities" cannot turn redaction into a wipe.

### The generated document

```markdown
---
name: auto-{scenario-slug}
description: "…what it does + when to use it + trigger words, as a class…"
metadata:
  author: "auto-skill"
  version: "3"
  scenario: "…problem class…"
  generated-at: "…"
  source-thread: "…"
  source-run: "…"
---

# {scenario}

> 本技能由 DeerFlow auto-skill 从真实运行轨迹自动沉淀生成（当前版本 v3，历史版本存于备份库）。
> 除「示例」外，正文只描述方法与路径，不绑定任何具体主体：换一个公司、一个报告期或一个地区同样适用。

## 适用场景      ← when_to_use
## 取数逻辑      ← data_fetching (ordered steps, parameter meanings, fallbacks)
## 推理逻辑      ← reasoning
## 回答格式      ← answer_format
## 示例          ← examples (only section that may name the run's subject)
## 注意事项      ← caveats (omitted when empty)
```

The header states the abstraction rule inside the published body on purpose: the
next update reads that body back as its "current skill" evidence, so the discipline
survives a rewrite instead of depending on the prompt alone. `## 示例` and
`## 注意事项` are omitted when the model returned nothing for them.

---

## Producer hook

`agents/middlewares/auto_skill_middleware.py`, appended by
`lead_agent/agent.py::build_middlewares` immediately after `MemoryMiddleware`
when `auto_skill.enabled`.

- **`after_agent` / `aafter_agent`** — the answer has already streamed, so this is
  off the user-visible path. It does only cheap in-memory work.
- **Lead chain only.** Never the subagent runtime base: a subagent trajectory is a
  fragment of the lead's, and learning from fragments would encode partial work as
  if it were a complete procedure.
- **Best effort by contract.** `_submit` wraps everything in `try/except` and logs
  with traceback. Skill learning is purely additive, so a corrupt checkpoint, a
  full queue or a programming error must never fail a run whose answer was already
  delivered.
- **Identity captured as data.** `user_id`, `thread_id`, `run_id` and `trace_id`
  are resolved in the hook, because the Timer thread inherits no ContextVars.
  `user_id` still matters even though the skill is global: it scopes the legacy
  sweep and the audit trail.

### Gates

| Gate | Effect |
|---|---|
| `auto_skill.enabled` false | no-op |
| no genuine user query | skip — nothing defines the scenario |
| no visible final answer | skip — no answer format to learn |
| successful tool calls < `min_tool_calls` | skip — no data-fetching path worth capturing |

Error-status tool results count as trajectory steps (they are evidence) but not as
successful calls, so a run where every tool failed is not learned.

---

## Trajectory extraction

`skills/auto/trajectory.py::extract_run_trajectory` reuses the platform's existing
message helpers rather than re-deriving provenance rules:

- **Query** — `latest_genuine_user_message` + `get_original_user_content_text`, so
  the learned scenario is the *user's* words, not the sanitization wrapper or an
  upload preamble.
- **Tool steps** — two passes correlating `AIMessage.tool_calls` with
  `ToolMessage` by `tool_call_id`, carrying name, args, result and status.
- **Matched skills** — the durable `ThreadState.skill_context` channel *plus* the
  `skill_usage` / `skill_usages` stamps, so both automatic loads and slash
  activations are captured; deduplicated, first-seen order.
- **Plan** — `ThreadState.todos` when plan mode ran.
- **Final answer** — the last `AIMessage` with visible content and no tool-call
  intent.

**Bounds.** Every field is truncated at capture time (query 2 000, answer 6 000,
args 800, each result `max_tool_result_chars`, at most 40 tool steps and 30
todos). `render_trajectory` then enforces `max_trajectory_chars`, dropping the
**oldest** tool steps first so the query and the final answer — the two facts that
define the scenario and its expected output — always survive.

`resolve_matched_auto_skills` re-checks each matched name against the global store
before echoing it to the model, so a retired or legacy per-user package is never
offered as "the current skill to improve".

Extraction never raises: a malformed checkpoint logs and returns `None`.

---

## Queue

`skills/auto/queue.py::AutoSkillQueue`, mirroring the memory backend's shape.

- **Batching never drops trajectories.** Debouncing *delays* the batch; every
  submitted request in the window is synthesized.
- **Bounded latency.** The timer arms on the first submit and is **not** rearmed,
  so continuous traffic cannot starve the drain the way a trailing-edge debounce
  would.
- **Bounded memory.** `queue_max_size` rejects the *new* submission when full
  rather than evicting queued work.
- **Fresh loop per batch.** `asyncio.run` gives the model call and the scanners
  their own loop-bound resources.
- **Config re-read at drain time.** A disable landing between enqueue and drain is
  honoured.
- **Failure isolation.** One raising synthesis does not stop the rest of the batch.
- **Drain.** `flush(timeout=...)` runs off-loop, cancels the pending timer, and
  reports how many trajectories it handed off.

Pending trajectories are lost on a crash — the same accepted trade-off the memory
queue makes. Graceful shutdown drains them via
`app/gateway/app.py::_flush_auto_skill_queue`, placed **before** the memory
backend closes because synthesis reads config and writes skills.

---

## Naming

`skills/auto/naming.py`. The slug normally comes from the synthesis model, which
sees the query and can name the scenario meaningfully. Model output is untrusted,
so it is normalized here (lowercase, non-alphanumeric runs collapsed to one
hyphen, trimmed), and a proposal that normalizes to nothing — a purely CJK
scenario name — falls back to `q` + the first 10 hex digits of SHA-256 over the
whitespace-collapsed, casefolded query. One scenario therefore keeps one stable
name instead of minting an unrelated skill per run.

The whole name must satisfy `SkillStorage.validate_skill_name` (hyphen-case, ≤ 64
chars) because it is also the package directory. The slug absorbs any overflow;
`name_prefix` is validated as hyphen-case and ≤ 32 chars at config load for the
same reason.

---

## Publication discipline

`store.write_skill(name, render=..., prune_keep=...)` follows the Lark installer's
pattern:

1. cross-process lock (`{integrations_root}/.auto-skill.write.lock`, `flock` /
   `msvcrt.locking`) plus an in-process `RLock`;
2. **`render` receives the authoritative version** — it is computed inside the
   lock, so two workers learning the same scenario cannot both decide on `v2` and
   lose one update;
3. private dot-prefixed staging directory under the integrations root (the leading
   dot keeps discovery from ever walking a half-written package);
4. write with `encoding="utf-8", newline=""` so the validated bytes are exactly
   the published bytes;
5. `parse_skill_file(..., SkillCategory.INTEGRATION, ...)` on those bytes, and the
   frontmatter `name` must equal the target;
6. `make_skill_tree_sandbox_readable` on the staged tree;
7. move the current package into the backup store;
8. one atomic `os.replace` into place;
9. on any failure after step 7, the backup is moved back, so a failed update never
   leaves the scenario without a visible skill.

### Legacy sweep

Earlier releases wrote per-user `{prefix}-{slug}-v{n}` packages into
`users/{uid}/skills/custom/`. Left alone they would sit beside the new global
package as duplicates. `sweep_legacy_user_skills(user_id, prefix, slug)` archives
them under the scenario's backup directory (prefixed `legacy-`, so version listing
and retention ignore them) and deletes them through the storage API, which owns
the projection lock.

Only packages whose frontmatter still carries `metadata.author: auto-skill` are
touched; an operator's hand-written skill matching the name pattern is left alone,
and so is anything unreadable. The sweep is idempotent and scoped to the scenario
being written.

### Bulk migration

The incremental sweep only fires for the scenario a run happens to reproduce, so a
deployment upgrading from the per-user versioned scheme can migrate everything at
once with `store.migrate_legacy_user_skills(user_id, prefix=...)`. It groups the
user's legacy packages by scenario and, per group:

- promotes the **highest** version to the global stable name — but only when no
  global package exists yet, because an existing one post-dates the migration
  boundary and is newer by definition, so it must not be clobbered by an older
  per-user copy;
- archives every version under `legacy-{user_id}-v{n}` in the backup store;
- deletes the per-user packages through the storage API.

It returns `{"promoted": [...], "archived": [...], "skipped": [...]}`, is
idempotent, skips anything not marked `author: auto-skill`, and never touches an
unrelated hand-written custom skill. Callers must invalidate caches afterwards
(`refresh_skills_system_prompt_cache_async()` + `publish_skills_cache_reset()` with
no `user_id`), since the store layer deliberately owns no cache policy.

---

## Security

Generated content passes the same four gates as agent-written content:

1. `SkillStorage.validate_skill_name`
2. frontmatter parse via `parse_skill_file`, with the `name` equality check
3. `enforce_static_scan` over the staged bytes — CRITICAL findings block
4. `scan_skill_content` — LLM moderation, given the static findings as context; a
   `block` decision publishes nothing. It reads
   `skill_evolution.moderation_model_name` and `skill_evolution.security_fail_closed`

The security scan runs on the *pre-lock* candidate. The version digit is assigned
inside the lock, so a concurrent writer can make the published content differ from
the scanned candidate by that one field; the scanned body is identical either way.

Rendering defends against the model forging structure: every section is stripped
of leading `---` lines (no second frontmatter block) and of a leading ATX heading
(the template already emits it, and models routinely repeat it — otherwise a
doubled `## 适用场景` ships in every generated skill); deeper sub-headings are
preserved. CRLF is normalized to LF. All scalar frontmatter values go through
`json.dumps`, which is always a valid YAML double-quoted scalar, so colons,
quotes, hashes and newlines in a model-provided `description` cannot break the
document.

---

## Cache invalidation

Because the package is global, caches are retired **without** a `user_id`:

```python
await refresh_skills_system_prompt_cache_async()      # this process, all users
await asyncio.to_thread(publish_skills_cache_reset)   # every peer process
```

A user-scoped marker would leave other users' per-`(app_config, user_id)` cache
entries serving a skill list that no longer matches disk. Write + refresh + publish
settle as one `await_drained` unit, so a cancelled worker cannot leave the package
published while caches stay stale. A publish failure is logged, not raised: the
package is already durable.

`SkillStorage.load_skills()` rescans disk on every call, so even without cache
invalidation the next agent assembly sees the change — invalidation exists to make
running processes converge promptly rather than eventually.

---

## Matching: learned skills are checked first

Publishing a skill is only half the feature — the next run has to find it. The
skills prompt therefore gives learned skills their own priority block, ahead of
everything else, and states the order explicitly:

1. check the learned skills for a scenario that matches this request;
2. load one (`describe_skill` → `read_file`, or `read_file` directly in the
   full-metadata mode) and follow it;
3. **then** decide whether another skill is still needed, and load one only when
   the matched learned skill does not cover the request.

Both discovery modes render it, because a deployment picks one via
`skills.deferred_discovery`:

| mode | block | contents |
|---|---|---|
| deferred (`true`) | `<auto_skill_index>` before `<skill_index>` | `name: description` — descriptions are resolved from the warm enabled-skills cache, because a learned skill's name is an English slug and a Chinese request would otherwise have nothing to match on |
| full metadata (`false`) | `<auto_skills>` before `<available_skills>` | the same `<skill>` entries, partitioned |

Membership is `name.startswith(f"{auto_skill.name_prefix}-")` within the enabled
set, gated on `auto_skill.enabled`; the prefix is read defensively (`getattr`) so
a partial config snapshot degrades to "no priority block" instead of raising
inside prompt assembly. A failed description lookup degrades to names only. The
index is bounded (`AUTO_INDEX_MAX_ENTRIES`, `AUTO_INDEX_DESCRIPTION_BUDGET`);
anything past the cap stays reachable through `describe_skill`. Values are
HTML-escaped like every other skill metadata render site, so a generated
description cannot close the tag and forge a framework block.

The legacy rendering is `lru_cache`d, so the prefix is part of the cache key.

---

## Configuration

```yaml
auto_skill:
  enabled: false                        # opt-in: this writes to a shared location
  model_name: null                      # null = default chat model
  name_prefix: "auto"                   # hyphen-case, <= 32 chars
  min_tool_calls: 1                     # skip runs with no data path
  max_trajectory_chars: 24000
  max_tool_result_chars: 2000
  debounce_seconds: 20
  max_versions: 5                       # backup versions kept per scenario
  queue_max_size: 64
  shutdown_flush_timeout_seconds: 30
```

Integer fields reject booleans through the shared `_boolean_guards.reject_boolean`
before Pydantic coerces `true` → `1`.

`auto_skill` is **hot-reloadable** and deliberately absent from
`STARTUP_ONLY_FIELDS`: the middleware is appended per agent assembly, so a toggle
applies on the next run without a restart.

Cost note: each learned skill costs one synthesis model call plus one moderation
scan — and `no_change` skips the scans entirely. Debouncing batches rapid turns,
and `min_tool_calls` keeps trivial chat-only runs from generating noise.

**Governance note.** Because the output is global, one user's run now shapes every
user's agent. The moderation scan, the `no_change` discipline and the
`min_tool_calls` gate are what keep that shared surface clean; the backup store
plus `restore_backup` are the recovery path when something bad does get published.

---

## Tests

| File | Covers |
|---|---|
| `tests/test_auto_skill_trajectory.py` | extraction, provenance preference, bounds, render budget |
| `tests/test_auto_skill_naming.py` | slug normalization, CJK fallback, stable-name budget, legacy version parsing |
| `tests/test_auto_skill_middleware.py` | gates, identity capture, async path, never-breaks-a-run |
| `tests/test_auto_skill_queue.py` | batching, bounded latency/memory, drain, failure isolation |
| `tests/test_auto_skill_store.py` | global visibility, backup/restore, retention, atomic publication, concurrency, legacy sweep, bulk migration |
| `tests/test_auto_skill_decision.py` | reason vocabulary, tool-diff evidence, the downgrade to `no_change` |
| `tests/test_auto_skill_abstraction.py` | entity normalization, leak detection, redaction ordering and bounds |
| `tests/test_auto_skill_synthesizer.py` | decision routing, update verification, abstraction gate, scenario index, JSON recovery, YAML-safe rendering, scan gates, global cache invalidation |
| `tests/test_auto_skill_prompt_priority.py` | the priority block in both discovery modes, bounds, escaping, degradation |
| `tests/test_auto_skill_config.py` | validation, reload boundary, lead-chain wiring |
| `tests/test_auto_skill_end_to_end.py` | the real chain with only the model stubbed |

The two suites that carry the requirements:

- `test_auto_skill_store.py::TestGlobalVisibility` and
  `test_auto_skill_end_to_end.py::TestGlobalSharing` drive the **real**
  `UserScopedSkillStorage` for several distinct users and assert a package written
  once is discoverable **and enabled** for all of them — the acceptance criterion
  for requirement 1. A skill that is written but not matchable by other users
  would pass every filesystem-level check and still fail the feature.
- `test_auto_skill_end_to_end.py::TestUpdateAndBackup` asserts that after an
  update exactly one package per scenario is visible to every user, the outgoing
  version is in the backup store, and `no_change` leaves the visible skill
  byte-identical — requirement 2.

The end-to-end suite stubs only `run_oneshot_llm` and the LLM moderation scan; the
deterministic SkillScan, the store's staging/backup/rename publication, and the
skill loader all run for real. It pins `DEER_FLOW_HOME` isolation by resetting the
`Paths` singleton and asserting the resolved `base_dir`, so the suite cannot
silently write into a developer's real runtime home.
