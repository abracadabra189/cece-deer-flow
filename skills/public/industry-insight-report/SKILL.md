---
name: industry-insight-report
display_name: 产业洞察报告
description: 生成产业洞察报告/产业发展状况报告/区域产业报告（@ 触发词：产业洞察、产业报告、区域产业、行业发展状况、批量报告）。当需要为"某地区 + 某产业"生成产业发展状况的产业洞察报告（MD/分页HTML/PDF）时使用。单报告模式：输入产业 code 与地区 code，按标准六阶段流水线生成并校验交付物。批量编排暂缓，未启用。
---

# 产业洞察报告（单报告流水线）

对 `(region_code, industry_code)` 生成一份产业洞察报告：`report.md` → 分页 `report.html` → `report.pdf`。
数据默认来自**本地 CECE MCP**（NER/enterprise/industry，见 `references/mcp-command-map.md`）；
HYDC 通道保留为 `--source hydc` 回退。公网补充默认**关闭**（`--public-web true` 才允许，且只用于框架调研，不用于数字）。

## 一键执行（确定性流水线）

```bash
python scripts/run_report.py --industry-code XHICC011005 --region-code 310000 \
  [--industry-name 类脑智能] [--region-name 上海市] [--as-of YYYY-MM-DD] \
  [--source mcp|hydc] [--out runs/<task_id>] [--fixture scripts/fixtures/sample_shanghai_brain.json] \
  [--public-web false]
```

- 默认 `--source mcp`：调用本地 MCP（自动探测 `127.0.0.1` / `host.docker.internal`，端口 18906/18907/18908；可用 `MCP_HOST` 覆盖）；
- `--source hydc`：历史通道，**本地部署已停用**（技能禁用 + overlay 禁止），仅 CLI 显式指定时可用；
- 无数据源凭据或离线开发/测试时用 `--fixture` 载入样例数据包。

### 本地 2026 栈内运行（agent bash）

本地 Gateway 以 LocalSandboxProvider 运行，bash 即容器内 shell；系统 `python` 没有 httpx，必须用网关 venv：

```bash
cd /app/skills/public/industry-insight-report
PYBIN=/app/backend/.venv/bin/python; [ -x "$PYBIN" ] || PYBIN=python3
$PYBIN scripts/run_report.py --industry-code 类脑智能 --region-code 310000 \
  --industry-name 类脑智能 --region-name 上海市 --source mcp \
  --out /mnt/user-data/outputs/industry-insight-report
```

- 产物写入 `/mnt/user-data/outputs`（本地 sandbox 自动映射到线程目录）；
- 2026 网关镜像已内置 **WeasyPrint 70 + Pango/HarfBuzz + Noto CJK 字体**，S5 在容器内直接产出 PDF（无 Chromium，不需要）；
  宿主 CLI 环境用 Playwright/Chromium，两套引擎页数校验一致；
- `sandbox.allow_host_bash` 必须为 `true`，否则 agent 无法执行任何脚本。
- 每阶段写 `progress.json`；失败退出码非 0，诊断在 stderr，产物路径在 stdout。
- 重跑自动跳过已 passed 阶段（断点续跑）。

## 阶段与门禁

| 阶段 | 动作 | 产物 | 门禁 |
| --- | --- | --- | --- |
| S0 需求拆解 | 实例化标准章节骨架（`references/report-structure.md`） | `spec.json` | 章节/数据需求/图表计划齐全 |
| S1 框架选择 | 按产业分类匹配 `references/frameworks/registry.json`，可组合 | `framework.json` | 每章有框架与分析逻辑链 |
| S2 取数 | `scripts/fetch_data_mcp.py`（默认）：本地 CECE MCP（NER 多体系解析 + industry 画像/评分/链条/创新/融资 + enterprise 企业榜）落 `raw_mcp/`，`normalize_mcp.py` 归一化；`--source hydc` 回退 cece-hydc-data。映射见 `references/mcp-command-map.md` | `raw_mcp/`、`data/*.json`、`data_manifest.json` | P0 数据集齐全或登记为数据限制 |
| S3 文稿 | 模板事实段 + 分析段（有 `REPORT_LLM_*` env 时走 P3 卡片，否则规则化分析段） | `report.md`、`narrative/` | 结构自检通过 |
| S3.5 数据校验 | `scripts/validate_data.py` 三层校验 + 文稿数字回溯 | `validation_report.json` | L1/L2 的 P0 与全部 L3 必须 pass |
| S4 渲染 | `scripts/render_charts.py`（SVG）+ `scripts/build_html.py`（分页） | `charts/`、`report.html` | 遵循 `references/html-rules.md` |
| S4.5 HTML 检查 | `scripts/check_html.py` 静态 lint + 可选无头度量 | `check_report.json` | 溢出/外链/缺块 = 0 |
| S5 PDF | `scripts/make_pdf.py`（Playwright，回退 WeasyPrint） | `report.pdf`、`pdf_check.json` | 页数与页眉校验通过；无引擎则降级交付 HTML |

> 生成前先自检取数：`python scripts/check_mcp.py --industry <产业> --region <code>`（三服务连通 + 产业解析 + 评分/画像试取）。P0 数据集缺失不再阻断（按数据限制降级），仅 L1/L2 实际数据错误与 L3 未命中数字阻断。

校验失败自动修复 ≤2 次（重取数 → 重写文稿）；图表失败降级为表格；P0 数据缺失任务 failed，不出 PDF。

## 交互模式（agent 逐步执行）

按上表逐阶段执行：S1 读 `references/frameworks/registry.json` 选框架（2–4 个互补、数据可得优先）；
S3 写作遵循 `references/prompts.md` 的 P3/P4 卡片与 `references/report-structure.md` 的分析推理规范；
交付前过 `references/self-check-list.md`。数字只允许来自 `data/` 或校验器派生值（零幻觉硬门）。

## 边界

- 不做批量编排（未启用）；不做企业筛选；不直连外部 API、不接触密钥（凭据由 operator env 配置）。
- `HYDC_API_KEY` 未配置时 S2 fail-fast 并给出配置指引（`.env` + 重启 Gateway；容器 sandbox 另注入 `sandbox.environment`）；离线用 `--fixture`。
- 空结果/报错视为数据限制，不等于"不存在"；缺口径明说，不推测填充。
