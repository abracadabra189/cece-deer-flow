# 产业洞察报告生成（industry-insight-report）

对"地区 × 产业"生成产业洞察报告：`report.md` → 分页 `report.html` → `report.pdf`。
实现载体为技能 `skills/public/industry-insight-report/`；当前启用**单报告模式**，批量编排未启用。

## 数据源（默认本地 CECE MCP）

- 默认 `--source mcp`：本地 FastMCP 服务（源码 `D:\project\毅达投资MCP\参考实现\entity_MCP`），
  NER `:18906`、enterprise `:18907`、industry `:18908`（PEVC `:18910`、person `:18911` 备用），
  启动方式 `start_servers.bat` 或逐个 `python servers/<x>_server.py`；
  Gateway 侧在根 `extensions_config.json` 的 `mcpServers` 配置，URL 用 `host.docker.internal`（Docker 2026 栈可达宿主）；
  宿主机 CLI 流水线走 `fetch_data_mcp.py` 的 `MCP_HOST=127.0.0.1`，与 Gateway 配置互不影响。
- **本地 2026 服务已停用 HYDC**：`extensions_config.json` 中 `cece-hydc-data` 为 `enabled=false`，
  `config.yaml` 的 lead_prompt_overlay 明确禁止 HYDC 查询；报告流水线默认 `--source mcp`，不回退 HYDC。
- **agent 执行条件**：本地 LocalSandbox 需 `sandbox.allow_host_bash: true`（当前已开启），否则 bash 工具不可用、
  技能只能被阅读不能执行；容器内须用 `/app/backend/.venv/bin/python`（系统 python 无 httpx）；产物写
  `/mnt/user-data/outputs`。2026 网关镜像已内置 WeasyPrint（含 Pango/HarfBuzz/Noto CJK），容器内可直接产出 PDF；
  宿主 CLI 使用 Playwright/Chromium，两套引擎均校验页数与页眉。
- `--source hydc` 仅为历史 CLI 通道（需 `HYDC_API_KEY`），本地部署不使用；`--fixture` 为离线样例包。
- 每报告约 10 次 MCP 调用（NER 1 + industry 8 + enterprise 1）；工具入参/出参见
  `skills/public/industry-insight-report/references/mcp-command-map.md`。

## 运行

```bash
# 真实数据（需 operator 配置 HYDC 凭据，见下）；industry-code 支持平台节点码（如 XHICC011005）或中文产业名（自动解析根节点）
python skills/public/industry-insight-report/scripts/run_report.py \
  --industry-code XHICC011005 --region-code 310000 --industry-name 类脑智能 --region-name 上海市

# 真实模式每报告固定 3 次 HYDC 调用（queryIndustries / queryIndustryProfile --all / queryParkProfile）；
# 平台精选子集不直出的展示点（ent_top、patent_value、fin_events 等）自动登记 limitation 并在方法论章声明。

# 离线/演示（样例数据包）
python skills/public/industry-insight-report/scripts/run_report.py \
  --industry-code BRAINLIKE --region-code 310000 \
  --fixture skills/public/industry-insight-report/scripts/fixtures/sample_shanghai_brain.json \
  --out runs/demo
```

可选参数：`--as-of`（数据截至日）、`--public-web true`（仅框架调研联网，默认关）、`--out`。
可选 env：`REPORT_LLM_BASE_URL/REPORT_LLM_API_KEY/REPORT_LLM_MODEL`（配置后分析段/摘要走 LLM prompt 卡片，否则规则化回退）。

## 阶段与产物（runs/<task_id>/）

S0 spec.json → S1 framework.json → S2 data/ → S3 report.md → S3.5 validation_report.json（硬门）
→ S4 charts/ + report.html → S4.5 check_report.json（硬门）→ S5 report.pdf + pdf_check.json。
`progress.json` 支持断点续跑；退出码 0=ok、1=门禁失败、2=数据全缺；PDF 无引擎时降级交付 HTML（status=degraded）。

## 版式与质量规则

- 封面/页眉/页脚/封底版式：`skills/public/industry-insight-report/references/html-rules.md`。
- 章节骨架与展示点：`references/report-structure.md`；图表映射：`references/chart-map.md`。
- 分析框架库（产业分类 ≤20 + 组合规则）：`references/frameworks/registry.json`。
- 数据校验规则（含文稿数字回溯防幻觉硬门）：`references/validation-rules.md`。

## PDF 引擎（S5）

本地启用 HTML→PDF：

```bash
pip install playwright pypdf
python -m playwright install chromium
```

（backend 容器/venv 环境等价于 `uv sync --extra browser && uv run playwright install chromium`。）
引擎缺失时 S5 自动降级交付 HTML（status=degraded），不阻断前序产物。

## 数据凭据（HYDC）与排障

- 凭据唯一入口：仓库 `.env` 的 `HYDC_API_KEY=<token>`（或 `Bearer <token>`）。Gateway 启动时经
  `deerflow.env.load_selected_env_file` 载入进程环境，LocalSandbox 的宿主机子进程继承；
  **修改后必须重启 Gateway**。容器/AIO sandbox 另需在 `config.yaml` 的 `sandbox.environment`
  增加 `HYDC_API_KEY: $HYDC_API_KEY`。
- 排障三步：
  1. `node skills/public/cece-hydc-data/scripts/hydc.mjs help` —— 报 "not configured" = 凭据未注入；
     报 "请使用有效的api key" = 凭据无效（网络与服务正常）；正常返回命令表 = 可用。
  2. 确认 `.env` 中 `HYDC_API_KEY` 非空（空值等同未配置）。
  3. 流水线侧：未配置凭据时 `fetch_data.mjs` 会 fail-fast 并提示配置方法；离线演示用 `--fixture`。
- `MCP_CECE_AUTH` 仅服务 CECE MCP server，与 HYDC 凭据相互独立；如 CECE 下发统一 token，可以同一值填入 `HYDC_API_KEY` 并用第 1 步验证。

## 测试

```bash
cd backend && python -m pytest ../tests/skills/industry-insight-report -q
```

离线运行（fixture + mock 传输）；E2E 覆盖全链路门禁与断点重跑。
