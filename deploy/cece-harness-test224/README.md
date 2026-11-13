# CECE Harness test224 deployment baseline

This directory holds the committed, secret-free configuration baseline for the `test224` environment.

Before deployment, copy the two templates to the deployment root using the runtime names below. Do not commit those runtime files or `.env`.

```bash
cp deploy/cece-harness-test224/config.example.yaml config.yaml
cp deploy/cece-harness-test224/extensions_config.example.json extensions_config.json
```

Populate `.env` with the values referenced by the templates, including `DASHSCOPE_API_KEY`, `DATABASE_URL`, and the enabled CECE MCP authorization variables. Each `Authorization` variable contains the complete header value, including any `Bearer ` prefix.

After changing `.env`, recreate the Gateway so its container receives the new environment:

```bash
docker compose --env-file .env -p cece-harness-test224 \
  -f docker/docker-compose.cece-harness-test224.yaml \
  -f docker/docker-compose.dood.yaml \
  up -d --no-deps --force-recreate gateway
```
