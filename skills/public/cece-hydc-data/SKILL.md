---
name: cece-hydc-data
description: Use when a CECE user needs enterprise, industry, market, policy, announcement, financing, or regional facts from the HYDC data service.
---

# CECE HYDC Data

Use this Skill as the sole business-data source in the dev172 environment. It calls the CECE-managed HYDC service through a fixed wrapper; credentials, endpoint, and timeout are supplied by the operator and are not model inputs.

## Invocation

Run the bundled script with Node. Do not copy the API key into a prompt, shell command, file, or output.

```bash
node /mnt/skills/public/cece-hydc-data/scripts/hydc.mjs help
node /mnt/skills/public/cece-hydc-data/scripts/hydc.mjs help "economicData help"
node /mnt/skills/public/cece-hydc-data/scripts/hydc.mjs query "economicData querySecuMain --keyword PAYH --limit 5"
```

The wrapper accepts only `help` or `query` plus the HYDC business command. Command parameters such as `--keyword`, `--limit`, dates, entity identifiers, and regions remain part of that business command.

## Query method

1. For an unfamiliar HYDC domain, use `help` once to verify command names, parameters, returned fields, and data scope.
2. Use the discovered command with the narrowest entity, date range, region, and result limit that answers the question.
3. Reuse a confirmed command schema rather than repeating `help`. Stop once the evidence is sufficient.

Use `references/commands.md` only as a discovery hint; live `help` is authoritative.

## Analysis boundaries

- State data scope and time range with factual conclusions.
- Separate retrieved facts from analysis and inference. Name missing data instead of filling gaps from guesswork.
- Treat an empty result, authorization failure, or service error as a data limitation, not evidence that an entity or event does not exist.
- The dev172 policy caps calls: ordinary questions up to 2, normal research up to 4, and user-requested deep research up to 8. Do not batch enumerate or query unrelated interfaces merely to appear comprehensive.

## Errors

- `HYDC_API_KEY is not configured`: the server operator must set the sandbox environment variable. Do not attempt a workaround.
- HTTP, non-JSON, or `success:false`: check the command with `help`, then narrow or correct the business parameters.
- Unknown command or field: use `help` to obtain the current schema; do not invent identifiers or URLs.
