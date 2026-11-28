---
name: cece-hydc-data
catalog_category: general_tool
reference_cases: []
starter_prompt: 请检索指定企业的基本信息、融资动态和主要经营风险，并注明数据来源。
starter_references: []
display_description: display_description_cece-hydc-data_ABC
example_queries:
  - cece-hydc-data_query1
  - cece-hydc-data_query2
  - cece-hydc-data_query3
display_name: CECE 产业数据
description: 当需要通过 HYDC 数据服务获取企业、行业、市场、政策、公告、融资或区域事实数据时使用。
---

# CECE HYDC 产业数据

本技能是 CECE 环境中唯一的业务事实数据来源。它通过固定封装调用 CECE 管理的 HYDC 服务；凭据、服务地址和超时时间由运维配置，不属于模型输入。

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
- The CECE deployment policy caps calls: ordinary questions up to 2, normal research up to 8, and user-requested deep research up to 16. Do not batch enumerate or query unrelated interfaces merely to appear comprehensive.

## Errors

- `HYDC_API_KEY is not configured`: the server operator must set the sandbox environment variable. Do not attempt a workaround.
- HTTP, non-JSON, or `success:false`: check the command with `help`, then narrow or correct the business parameters.
- Unknown command or field: use `help` to obtain the current schema; do not invent identifiers or URLs.
