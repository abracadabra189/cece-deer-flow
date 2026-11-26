# 产业洞察报告功能 — 工作量说明（工时填报用）

- 日期：2026-11-24
- 范围：`skills/public/industry-insight-report/` 全量交付（方案、代码、测试、部署集成、文档）
- 说明：本文给出功能说明、方案设计、实现代码、评估测试与逐项工时；工时按"独立完成该交付物"的等效投入估算，并附日历填报口径。

---

## 一、功能说明

对 `(地区, 产业)` 自动生成产业发展状况报告，输出 `report.md → 分页 report.html → report.pdf`，面向批量交付场景设计，当前启用单报告模式。

### 1.1 输入 / 输出

| 项 | 内容 |
| --- | --- |
| 输入 | 产业 code（或中文产业名，自动解析节点）、地区行政区划 code；可选 as-of、数据源、输出目录 |
| 输出 | `report.md`、`report.html`（A4 分页、封面/页眉页脚/封底、图表内联 SVG）、`report.pdf`；`validation_report.json`、`check_report.json`、`progress.json`、`raw*/`、`data/`、`charts/` |
| 数据源 | 默认本地 CECE MCP（NER/enterprise/industry，每报告约 10 次调用）；HYDC 为历史通道（本地部署已停用）；支持 `--fixture` 离线样例 |
| 语言/版式 | 中文；A4 210×297mm；正文五章 + 摘要/方法论/结论/附录；每图每表带"截至 + 数据来源" |

### 1.2 流水线（S0–S5）

| 阶段 | 动作 | 产物 | 门禁 |
| --- | --- | --- | --- |
| S0 需求拆解 | 实例化标准章节骨架、数据需求、图表计划 | `spec.json` | 章节/需求/计划齐全 |
| S1 框架选择 | 按产业分类匹配框架库，可组合 | `framework.json` | 2–4 个互补框架、章→框架映射 |
| S2 取数 | MCP（NER 解析 + industry 8 工具 + enterprise 企业榜）→ 归一化 | `raw_mcp/`、`data/*.json`、`data_manifest.json` | P0 数据集齐全或登记 limitation |
| S3 文稿 | 模板事实段 + 分析段（可选 LLM）→ MD + 结构化 blocks | `report.md`、`blocks.json` | 结构自检 |
| S3.5 校验 | L1 schema / L2 一致性 / L3 文稿数字回溯 | `validation_report.json` | 硬门；失败自动修复 1 次 |
| S4 渲染 | 11 类 SVG 图表 + 分页 HTML（装箱、表跨页） | `charts/`、`report.html` | 遵循 html-rules |
| S4.5 检查 | 静态 lint + Playwright 无头溢出度量 | `check_report.json` | 外链/溢出/缺块 = 0 |
| S5 PDF | Playwright 优先、WeasyPrint 回退，页数/页眉校验 | `report.pdf`、`pdf_check.json` | 页数=HTML 页数；无引擎降级 |

### 1.3 质量特性
- 零幻觉硬门：MD 中每个数字必须命中数据包或校验器派生值，否则阻断；
- 断点续跑：`progress.json` 跳过已通过阶段；重跑幂等；
- 优雅降级：图表失败→表格、无 PDF 引擎→HTML、平台不直出展示点→limitation 并在方法论章声明；
- 可移植：脚本纯 Python 标准库 + httpx（MCP），无 Node 依赖（HYDC 通道除外）。

---

## 二、方案设计

### 2.1 总体架构

```
run_report.py（编排/门禁/断点）
 ├─ S0 spec 实例化（标准五章 + 增强三章）
 ├─ S1 framework.json（产业分类 → 框架组合）
 ├─ S2 fetch_data_mcp.py → normalize_mcp.py（或 fetch_data.mjs → normalize_data.py）
 ├─ S3 blocks 生成 → report.md（事实段模板 + 分析段规则/LLM）
 ├─ S3.5 validate_data.py（L1/L2/L3）
 ├─ S4 charts_svg.py + render_charts.py + build_html.py
 ├─ S4.5 check_html.py（静态 + 无头）
 └─ S5 make_pdf.py（Playwright / WeasyPrint）
```

### 2.2 关键设计决策
| 主题 | 决策 |
| --- | --- |
| 承载形式 | 新建 public skill（工作流 + 确定性脚本），不进 core；配置/密钥走 operator env |
| 图表引擎 | 内置纯 Python SVG（离线、打印稳定、无 JS）；ECharts/AntV 不进入 PDF 链路 |
| 分页模型 | 固定 `.page` A4 容器 + 块高度估算装箱；表格按行切分并重复表头；页眉页脚为每页重复 DOM |
| 数据校验 | 三层 + 派生值白名单；P0 失败阻断；L3 未命中即阻断；附录图号序列豁免 |
| 数据源抽象 | 统一 `data/*.json` schema；HYDC 与 MCP 各自归一化，下游渲染不变 |
| 部署 | dev172 基线同步；本地 2026 栈用 `host.docker.internal` 访问宿主 MCP；CLI 用 127.0.0.1 |

### 2.3 报告样例规范（对齐样张 + 增强）
封面（logo/报告名/主题/章节导航/免责句）、正文页眉（左 logo+平台名，右"产业洞察报告"）、页脚页码；
正文五章（产业评分/图谱/企业画像/产业创新/产业发展），新增执行摘要、方法论与数据口径、结论与建议、附录（指标定义/图表索引）；
每图每表"截至 + 数据来源"；表格跨页重复表头、数值右对齐；分析按"观察→归因→含义"三段，事实与推断分离。

### 2.4 框架库
20 个产业分类（新一代信息技术、集成电路、人工智能、未来产业、生物医药…建筑与智能建造）、15 个框架
（六维评分卡、价值链、钻石模型、五力、PESTEL、生命周期、四链融合、产业链韧性、TAM-SAM-SOM、BCG、GE-McKinsey、Gartner、专利价值、SWOT、MGI 赛道），
3 条组合规则（区域产业复合/未来产业复合/需求侧复合），含来源引用与"数据可得优先"降级规则；运行时只读、变更走 PR。

### 2.5 中间 Prompt 卡片
P0 需求实例化 / P1 需求拆解 / P2 框架选择 / P2b 框架联网调研（默认关）/ P3 章节分析段（What-Why-SoWhat、零幻觉）/ P4 摘要结论 / P5 失败修复；
无 LLM 时规则化回退，保证离线可跑且 L3 必过。

---

## 三、实现代码

### 3.1 规模
- 技能 32 个文件：Python 12 个 **2,496 行**、Node 1 个 118 行、Markdown 9 个 360 行、JSON/资产 6 个；
- 测试 4 个文件 196 行（9 个用例）；
- 文档 2 篇 324 行（方案 + 用户指南）。

### 3.2 模块清单
| 模块 | 职责 | 行数 |
| --- | --- | --- |
| `run_report.py` | S0–S5 编排、门禁、断点、降级、MD/blocks 生成 | 680 |
| `mcp_client.py` | MCP Streamable-HTTP 客户端（initialize/tools/call，SSE 解析） | 95 |
| `fetch_data_mcp.py` | NER 产业解析 + industry/enterprise 取数，host 自动探测 | 110 |
| `normalize_mcp.py` | MCP 出参 → 15 类报告数据集，口径校正与 limitation | 230 |
| `validate_data.py` | L1/L2/L3 校验、派生值白名单、门禁退出码 | 200 |
| `charts_svg.py` | 11 类 SVG 图表（评分条/雷达/树/柱/堆叠/双轴/折线/环图/金字塔/条形/气泡矩阵） | 400 |
| `render_charts.py` | 图表 spec 构建与落盘（charts.json + SVG） | 120 |
| `build_html.py` | 分页装箱、封面/页眉页脚/封底、表格跨页、单文件自包含 | 250 |
| `check_html.py` | 静态 lint + 无头溢出度量 | 90 |
| `make_pdf.py` | Playwright/WeasyPrint 双引擎、页数/页眉校验 | 90 |
| `llm_client.py` | OpenAI 兼容客户端（可选分析段） | 40 |
| `fetch_data.mjs` | HYDC 传输包装（--fixture/鉴权 fail-fast/路径回退） | 118 |
| `normalize_data.py` | HYDC groups → 数据集，分档补齐与占比重算 | 230 |
| 资产/模板 | logo、封面波浪、主题 tokens、二维码占位、样例数据包 | — |

### 3.3 测试代码
`test_validate_data.py`（正/反例、L1 阻断）、`test_build_html.py`（分页/表头重复/检查）、
`test_charts_svg.py`（11 渲染器 + 环图合并）、`test_pipeline_e2e.py`（fixture 全链路 + 幂等重跑）。

---

## 四、评估与测试

### 4.1 测试结果
| 场景 | 数据源 | 结果 |
| --- | --- | --- |
| 离线单测 | — | 9/9 passed（含无头溢出检查） |
| fixture 全链路 | 样张数据包 | 19 页、15 图、validation/check 通过 |
| 真实数据（HYDC） | 上海×类脑智能 | 13 页、11 图、PDF 13 页（Playwright） |
| 真实数据（MCP） | 上海×类脑智能 | 15 数据集、16 页、9 图、validation 0 失败、PDF 16 页 |
| 沙箱镜像（base-v1） | HYDC | S0–S5 全过、WeasyPrint PDF 13 页 |
| 2026 网关容器内 | MCP | 流水线可执行，S5 因无引擎降级 HTML |

### 4.2 过程中发现并修复的缺陷（节选）
1. 产业链树 px→mm 系数错误（估 33mm/实 119mm）→ 溢出根因；
2. `.content` 盒高与装箱常量不一致（225 vs 243mm）；
3. 表格行高估算偏低（7→8mm/行，表头 9mm）；
4. WeasyPrint 压缩对象流导致页数正则失效 → 改用 render API；
5. NER 出参字段（产业代码/产业类型）与假设不符 → 解析修正；
6. MCP 评分维度字段为"评分/区域排名"、专利为"专利总量/名称/数量" → 映射修正；
7. 容器内 `python` 无 httpx / MCP 127.0.0.1 不可达 → venv python + 主机自动探测；
8. 双 Gateway 共用 SQLite 导致 disk I/O 错误、记忆索引损坏 → 停宿主栈、重建索引；
9. HYDC 凭据为空 + 示意命令与真实 schema 不符 → 诊断注入 + 按 live help 校准；
10. `--source` 接线、企业榜空值、机构榜排序等渲染健壮性问题。

---

## 五、工作量明细（等效投入）

> 口径：按"独立完成该交付物"的等效工时估算（含设计、编码、调试、验证）；AI 辅助压缩了日历时间，不改变交付物范围。

| 阶段 | 任务 | 交付物 | 工时(h) |
| --- | --- | --- | --- |
| **一、需求与方案设计** | | | **34** |
| | 需求拆解与样张分析（19 页版式/展示点） | 需求清单、样张拆解 | 5 |
| | 市场分析框架调研与产业分类（20 类/15 框架/组合规则/来源） | `frameworks/registry.json` | 8 |
| | 报告样例规范（封面/页眉页脚/章节/表格/推理规则） | `report-structure.md` | 6 |
| | 流水线与契约设计（S0–S5/门禁/断点/降级） | `SKILL.md`、契约 | 7 |
| | HTML 分页/图表/校验/Prompt 规则设计 | `html-rules.md`、`chart-map.md`、`validation-rules.md`、`prompts.md` | 8 |
| **二、取数与文稿实现** | | | **41** |
| | 技能骨架与引用文档 | SKILL + references | 5 |
| | MCP 客户端/取数/归一化 | `mcp_client.py`、`fetch_data_mcp.py`、`normalize_mcp.py` | 12 |
| | HYDC 通道包装与归一化（保留回退） | `fetch_data.mjs`、`normalize_data.py` | 8 |
| | 数据校验三层 + 门禁 + 修复策略 | `validate_data.py` | 8 |
| | 文稿生成（模板事实段/分析段/摘要/附录/图表索引） | `run_report.py`（S3） | 8 |
| **三、渲染实现** | | | **30** |
| | 11 类 SVG 图表引擎 | `charts_svg.py`、`render_charts.py` | 10 |
| | 分页 HTML（封面/页眉页脚/装箱/表跨页/单文件） | `build_html.py` | 10 |
| | HTML 检查（静态 + 无头） | `check_html.py` | 4 |
| | PDF 双引擎 + 校验 | `make_pdf.py` | 4 |
| | 品牌资产与主题 | logo/波浪/theme/QR | 2 |
| **四、测试与评估** | | | **22** |
| | 离线单测（9 用例） | `tests/skills/...` | 5 |
| | fixture E2E 与缺陷修复 | 19 页验收 | 6 |
| | live HYDC 校准（命令/字段/口径，3 轮） | 13 页验收 | 5 |
| | live MCP 校准（字段/分档/事件/榜单） | 16 页验收 | 4 |
| | 无头溢出校准与回归 | 0 溢出 | 2 |
| **五、部署与集成** | | | **20** |
| | dev172 配置同步（overlay/README/文档） | 基线 + runtime | 3 |
| | HYDC 凭据诊断与注入 | 鉴权打通 | 2 |
| | 本地 MCP 五服务部署与配置切换（含 resolver 语义排查） | 127.0.0.1/host.docker.internal | 5 |
| | 2026 服务重建、DB 冲突与记忆索引修复 | healthy + 数据完好 | 4 |
| | 本地调用链排障（allow_host_bash/venv python/MCP host） | 技能可执行 | 4 |
| | 前端镜像重建与 UI/API 验证 | @ picker 同步 | 2 |
| **六、文档与交付** | | | **5** |
| | 用户指南、MCP 映射、工作说明 | `docs/guide/...` 等 | 5 |
| **合计** | | | **152 h ≈ 19 人日** |

### 5.1 按日填报建议（若系统必须填具体日期）
| 日期 | 主要工作 | 填报 |
| --- | --- | --- |
| 11-20 | 需求拆解、框架调研、方案与规范设计 | 8 h |
| 11-21 | 技能骨架、取数与归一化、校验、文稿 | 8 h |
| 11-22 | 图表/HTML/PDF、单测与 fixture 验收 | 8 h |
| 11-23 | 真实数据（HYDC）联调、dev172 集成、凭据排障 | 8 h |
| 11-24 | MCP 切换、2026 服务重建与排障、文档 | 8 h |
| **合计** | | **40 h** |

> 说明：40 h 为按日历的填报口径；152 h 为独立完成同等交付物的等效工作量（含全部调试与返工），两者不重复填报。若组织允许按任务量申报，建议采用明细表；若必须按日期，采用上表。

---

## 六、交付物清单

| 类别 | 路径 |
| --- | --- |
| 技能 | `skills/public/industry-insight-report/`（SKILL.md、references×9、scripts×12、assets、fixtures） |
| 测试 | `tests/skills/industry-insight-report/`（4 文件 9 用例） |
| 方案 | `docs/plans/2026-11-20-industry-insight-report-pipeline.md` |
| 指南 | `docs/guide/industry-insight-report.md` |
| 部署配置 | `deploy/cece-harness-dev172/`（基线 + runtime）；根 `config.yaml` / `extensions_config.json` / `docker/docker-compose.yaml` |
| 样例产物 | 运行目录 `report.md` / `report.html` / `report.pdf`（16 页，MCP 数据源） |

## 七、后续可选（未计入本次工时）
- 批量编排（manifest/并发/汇总，方案已预留契约）；
- 2026 网关镜像内安装 Chromium/WeasyPrint 以获得原生 PDF；
- MCP 平台补齐 ent_structure / fin_index / 专利细分 / 融资轮次等展示点；
- 前端 @ picker 的二次验证与 Next.js 安全升级。