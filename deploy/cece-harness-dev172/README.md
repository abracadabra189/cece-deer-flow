# CECE Harness dev172 deployment baseline

This directory holds the committed, secret-free configuration baseline for the `dev172` environment.

Before deployment, copy the two templates to the deployment root using the runtime names below. Do not commit those runtime files or `.env`.

```bash
cp deploy/cece-harness-dev172/config.example.yaml config.yaml
cp deploy/cece-harness-dev172/extensions_config.example.json extensions_config.json
```

Populate `.env` with the values referenced by the templates, including `DASHSCOPE_API_KEY`, `DATABASE_URL`, and `HYDC_API_KEY`. `HYDC_API_KEY` is injected into sandbox containers only for the CECE HYDC Data Skill; do not put it in a prompt, a command-line argument, or a tracked file. The CECE MCP authorization variables remain documented in the extensions template but are not needed while those MCP servers are disabled.

Two session variables belong in `.env` as well:

- `AUTH_JWT_SECRET` pins the session/ticket signing key. Without it the Gateway generates `{DEER_FLOW_HOME}/.jwt_secret` and warns at startup, so losing or moving that home volume logs **every** user out at once. Set it explicitly, and use a **different value per environment** — one shared key would let a token minted by one environment pass signature checks in another.
- `DEER_FLOW_AUTH_ALLOW_INSECURE_PERSISTENT_COOKIE=1` makes the session cookie persistent over plain HTTP. Without it, a browser that reaches this deployment by IP or hostname over HTTP receives a session-scoped cookie and is signed out the moment the browser closes (mobile browsers evict it even sooner). The alternative is terminating HTTPS in front of nginx, which is the better long-term answer.
- `GATEWAY_ENABLE_DOCS=false` (the Compose default for this baseline) disables `/docs`, `/redoc` and `/openapi.json`. A penetration test against a public host found the OpenAPI schema reachable without authentication: nginx proxies those three routes to the Gateway and the auth middleware lists them as public, so this toggle is the only barrier. Keep it false on anything internet-reachable; if engineers need the schema, set it true in the deployment dotenv and expose it only through the internal network or a VPN.

The Compose file passes both through `environment:` so this stack uses its own values even though the repository-root `.env` is also loaded as an `env_file`.

After changing `.env`, recreate the Gateway so its container receives the new environment. Use the isolated dev172 Compose file at `docker/docker-compose.cece-harness-dev172.yaml`; do not use the test224 Compose file.

```bash
docker compose --env-file .env -p cece-harness-dev172 \
  -f docker/docker-compose.cece-harness-dev172.yaml \
  -f docker/docker-compose.dood.yaml \
  up -d --no-deps --force-recreate gateway
```

## External-only sign-in (`auth.local`)

This baseline closes both local-auth gates, so the external user system is the only way in:

| Setting | Value | Effect |
|---|---|---|
| `auth.local.allow_registration` | `false` | `POST /api/v1/auth/register` → `403 registration_disabled` |
| `auth.local.password_login_enabled` | `false` | `POST /api/v1/auth/login/local` → `403 password_login_disabled`, ahead of the login throttle and of any credential check; `/setup-status` reports it and the login page replaces the password form with a notice |

Both live in `config.yaml` and are hot-reloadable, and neither revokes an already-issued session cookie — flipping them on a running deployment does not log anybody out. `/initialize` stays open, so a fresh install can still create its first admin.

Because there is no self-service way back in, two invariants must hold:

- `auth.external_user.admin_phones` is the **only** admin path once password login is closed, so keep at least one account in it (this baseline lists the two operator numbers). Role is decided when an account is *provisioned*, so add the entry before that account's first provision — an existing `user` row is not upgraded by a later call.
- Any 401 lands the browser on `/login`, which now offers no way in. The integrating system must own re-entry: generate `login_url` at click time (tickets live 120s) and open it as a top-level navigation, never inside an iframe, where `SameSite=Lax` cookies are not sent.

The rest of the session-durability checklist — cookie persistence over HTTP, the JWT secret, ticket TTL, `session_expiry_minutes`, account disable, `reset_admin.py` — is in `docs/EXTERNAL_USER_INTEGRATION.md` §3.6.

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

## Industry insight report pipeline (`industry-insight-report`)

- 触发："区域产业洞察报告 / 产业发展状况报告"等标准化交付请求（含批量清单）；输入仅产业 code（或中文产业名）+ 地区 code。策略段见 `config.example.yaml` 的 `lead_prompt_overlay`。
- Composer `@` 提及：技能为 public 且默认 enabled，`GET /api/skills` 即列出；description 内含中文触发词（产业洞察/产业报告/区域产业/行业发展状况/批量报告）供 picker 搜索与 deferred discovery 匹配。若中文命中弱，可按上文 `skills.deferred_discovery` 一节切换为全描述注入。
- 流水线与硬门见技能 `skills/public/industry-insight-report/SKILL.md`：S0–S5（框架匹配 → 取数 → MD → 数据校验 → 分页 HTML → HTML 检查 → PDF），validation/check 失败即如实交付。
- 取数复用 cece-hydc-data 传输与本文的 `HYDC_API_KEY` 沙箱注入；每报告固定 3 次调用（queryIndustries / queryIndustryProfile --all / queryParkProfile），命令 schema 见技能 `references/hydc-command-map.md`。
- 制品落 `/mnt/user-data/outputs`（report.md / report.html / report.pdf）。`cece-harness-sandbox:base-v1` 内置 WeasyPrint 与 Noto CJK 字体（无 Chromium），S5 走 WeasyPrint 回退路径出 PDF（页数由 render API 直取）；两者皆缺时才降级交付 HTML 并在 `pdf_check.json` 声明。
- 展示点边界：平台聚合画像不直出 ent_top / patent_value / patent_tech / patent_region / patent_applicant / fin_round / fin_events / fin_inst 八类展示点，技能登记 limitation 并在方法论章声明，不补造数据。
- 部署后验证（沙箱 prewarm 完成后）：
  `docker exec <cece-harness-sandbox-*> sh -c 'printenv HYDC_API_KEY | wc -c; node /mnt/skills/public/cece-hydc-data/scripts/hydc.mjs help | head -c 80'`

## Recursion limit

The template sets `recursion_limit: 1000` (equal to the default `max_recursion_limit`). The middleware chain consumes several LangGraph super-steps per logical turn, and HYDC research often needs `help` plus several `query` calls; the previous default could exhaust the step budget before a final answer was produced, and a truncated run has no learnable answer for auto-skill. Cost remains bounded by `token_budget.max_tokens`.
