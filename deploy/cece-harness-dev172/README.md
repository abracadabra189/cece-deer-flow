# CECE Harness dev172 deployment baseline

This directory holds the committed, secret-free configuration baseline for the `dev172` environment.

Before deployment, copy the two templates to the deployment root using the runtime names below. Do not commit those runtime files or `.env`.

```bash
cp deploy/cece-harness-dev172/config.example.yaml config.yaml
cp deploy/cece-harness-dev172/extensions_config.example.json extensions_config.json
```

Populate `.env` with the values referenced by the templates, including `DASHSCOPE_API_KEY`, `DATABASE_URL`, `HYDC_API_KEY`, and `EXTERNAL_USER_API_KEY_DEV172`. `HYDC_API_KEY` is injected into sandbox containers only for the CECE HYDC Data Skill; do not put it in a prompt, a command-line argument, or a tracked file. `EXTERNAL_USER_API_KEY_DEV172` guards the external user-provisioning endpoint described below — treat it as an admin credential. The CECE MCP authorization variables remain documented in the extensions template but are not needed while those MCP servers are disabled.

After changing `.env`, recreate the Gateway so its container receives the new environment. Use the isolated dev172 Compose file at `docker/docker-compose.cece-harness-dev172.yaml`; do not use the test224 Compose file.

```bash
docker compose --env-file .env -p cece-harness-dev172 \
  -f docker/docker-compose.cece-harness-dev172.yaml \
  -f docker/docker-compose.dood.yaml \
  up -d --no-deps --force-recreate gateway
```

## External user-system integration (`auth.external_user`)

This baseline enables phone-based provisioning so CECE's existing user system can send users in without a second registration. Two endpoints, both public in the auth middleware and self-authenticating:

```bash
# Server-to-server: resolve-or-register by phone, returns credentials.
# <PORT> is the nginx ingress from .env (default 2026; the local runtime in
# deploy/cece-harness-dev172/runtime/.env uses 2027 to avoid the deer-flow stack).
curl -sS -X POST http://<host>:<PORT>/api/v1/auth/external/provision \
  -H "X-External-User-Key: $EXTERNAL_USER_API_KEY_DEV172" \
  -H 'Content-Type: application/json; charset=utf-8' \
  -d '{"phone":"+8613800138000","username":"张三","next":"/workspace/chats"}'
# → { user_id, created, email, system_role, access_token, expires_in, login_ticket, login_url }
```

Hand `login_url` to the browser: `GET /api/v1/auth/external/login?ticket=…` spends the ticket once, sets the `access_token` / `deerflow_session_persistent` / `csrf_token` cookies, and 302s to `/auth/callback?next=…`, so the user lands signed in with no frontend change. Any failure (missing, forged, expired, replayed ticket, or a disabled account) redirects to `/login?error=external_login_failed` without setting a cookie.

Operator notes for this environment:

- The key is `EXTERNAL_USER_API_KEY_DEV172`, deliberately **not** the `EXTERNAL_USER_API_KEY` other environments use, so one leak cannot open both. It is worth an account for *any* phone number: keep it in `.env`, expose the endpoint only on the trusted network, and rotate by changing the value and recreating the Gateway.
- Accounts are linked as `(oauth_provider=external-phone, oauth_id=<normalized phone>)` with a derived `users.email` of `{phone}@users.deerflow.internal` and **no password**, so password login stays impossible for them and the external system owns their authentication. The supplied `username` is stored as the `external_username` user preference.
- A phone already owned by an unrelated local account answers `409` rather than being seized; a disabled account answers `403`.
- `auth.external_user.*` is hot-reloadable, but the key lives in `.env`, so rotating it requires `--force-recreate gateway`.
- Full flow, field tables and the integration checklist: `docs/EXTERNAL_USER_INTEGRATION.md`; HTTP contract: `backend/docs/API.md#external-user-provisioning`.

## Automatic skill synthesis (`auto_skill`)

The template enables post-run skill synthesis. After a completed run that made at least one successful tool call, the Gateway distils the run's data-fetch path (tools, arguments), reasoning logic, and answer format into a reusable `SKILL.md`. It is a pure side effect: extraction is in-memory, synthesis and writes happen on a background thread after a debounce window, and any failure is logged and dropped without touching the delivered answer.

Generated skills are published globally so every user sees the same version. Paths below use the host-side `DEER_FLOW_HOME` from `.env`; inside the Gateway container the same tree is `/app/backend/.deer-flow`:

- Current skill: `{DEER_FLOW_HOME}/integrations/skills/auto-skill/{name}/SKILL.md`
- Backups: `{DEER_FLOW_HOME}/auto-skill-backup/{name}/v{n}/SKILL.md`

`{name}` is stable (`{name_prefix}-{scenario-slug}`); updates replace the published body and move the previous version into the backup library instead of creating a new visible skill. The synthesizer model decides `create` / `update` / `no_change` per run, so repeated questions converge on one skill. Published bodies pass four gates: skill-name validation, frontmatter parsing, deterministic `SkillScan`, and optional LLM moderation (`skill_evolution.moderation_model_name`); with `skill_evolution.security_fail_closed: true`, an unavailable moderation model rejects the write rather than letting it through.

Two further quality gates apply before anything is written:

- **An `update` is verified, not trusted.** It must name at least one substantive reason (`new_tool`, `new_flow`, `answer_format`, `new_dimension`, `correction`, `fallback`), and `new_tool` is dropped unless the platform's own tool diff finds a tool the skill's text does not mention. A run that only differs in subject, values or wording (`examples_only` / `data_values` / `wording`) degrades to `no_change`, so a solved scenario is not rewritten on every run.
- **Generated bodies stay abstract.** Concrete entities (company/person/product/place names, codes, dates, amounts) may appear only in the `## 示例` section; `scenario`, `description` and the method sections describe a class of questions. A leak gets one repair attempt and is then redacted to `【实体】`. This keeps one skill usable for the next company in the same scenario.

Learned skills are also matched first: the system prompt lists them ahead of every other skill and instructs the agent to check them, then decide whether another skill is still needed. In this baseline `skills.deferred_discovery: true` renders that priority block *with descriptions*, which is what makes Chinese requests match an English slug.

`skill_evolution.enabled` must stay `false` here: it gates the agent-facing skill write tool, not auto-skill. Auto-skill borrows only the moderation settings.

`auto_skill` is hot-reloadable: toggling `enabled` applies on the next run, without a Gateway restart. The configured `model_name` must exist in `models[]`.

### Interaction with `skills.deferred_discovery`

This baseline sets `skills.deferred_discovery: true`, so the system prompt contains only a compact `<skill_index>` (skill names) and the agent fetches descriptions on demand. Auto-generated names are English slugs (for example `auto-enterprise-shareholder-structure`), which match Chinese questions weakly at the name-only level. If generated skills are not being picked up for Chinese queries, set `skills.deferred_discovery: false` to inject full descriptions (including Chinese trigger words) into the prompt. Both settings are hot-reloadable.

### Verification and rollback

1. Ask a question that requires the HYDC skill and completes normally.
2. Wait at least `debounce_seconds`, then check the Gateway log: `docker logs cece-harness-dev172-gateway 2>&1 | grep "auto-skill"` (or the deployment's equivalent log source). Successful publications log `auto-skill published <name> v<n>`; a run that added nothing logs `auto-skill no_change ...`; a claimed update that failed verification logs `auto-skill update downgraded to no_change for <name>: ...`; a forced abstraction fix logs `auto-skill <name> redacted concrete entities from ...`.
3. Confirm the skill appears in `GET /api/skills` under the `integrations` category and in the filesystem path above.

To roll back, set `auto_skill.enabled: false` (effective next run) and delete `{DEER_FLOW_HOME}/integrations/skills/auto-skill` plus `{DEER_FLOW_HOME}/auto-skill-backup`. Individual scenarios can be restored from `auto-skill-backup/{name}/v{n}/`.

## Recursion limit

The template sets `recursion_limit: 1000` (equal to the default `max_recursion_limit`). The middleware chain consumes several LangGraph super-steps per logical turn, and HYDC research often needs `help` plus several `query` calls; the previous default could exhaust the step budget before a final answer was produced, and a truncated run has no learnable answer for auto-skill. Cost remains bounded by `token_budget.max_tokens`.
