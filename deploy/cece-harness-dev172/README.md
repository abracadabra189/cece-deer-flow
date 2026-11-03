# CECE Harness dev172 deployment baseline

This directory holds the committed, secret-free configuration baseline for the `dev172` environment.

Before deployment, copy the two templates to the deployment root using the runtime names below. Do not commit those runtime files or `.env`.

```bash
cp deploy/cece-harness-dev172/config.example.yaml config.yaml
cp deploy/cece-harness-dev172/extensions_config.example.json extensions_config.json
```

Populate `.env` with the values referenced by the templates, including `DASHSCOPE_API_KEY`, `DATABASE_URL`, and `HYDC_API_KEY`. `HYDC_API_KEY` is injected into sandbox containers only for the HYDC Skill; do not put it in a prompt, a command-line argument, or a tracked file. The CECE MCP authorization variables remain documented in the extensions template but are not needed while those MCP servers are disabled.

After changing `.env`, recreate the Gateway so its container receives the new environment. The Compose file belongs in `docker/`; this branch does not yet carry a `docker-compose.cece-harness-dev172.yaml`, so create or select the dev172-specific Compose file before deployment rather than using the test224 file.

```bash
docker compose --env-file .env -p cece-harness-dev172 \
  -f docker/docker-compose.cece-harness-dev172.yaml \
  -f docker/docker-compose.dood.yaml \
  up -d --no-deps --force-recreate gateway
```
