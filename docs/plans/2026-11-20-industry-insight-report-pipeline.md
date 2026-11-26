# 产业洞察报告批量生成流水线 — 实施方案（待评审）

- 状态：**已评审通过并实现（单报告模式）**（2026-11-20）。批量编排（§3.3 batch_run.py）按评审结论暂缓；
  公网补充默认关闭；PDF 引擎缺失时降级交付 HTML。实现位于 `skills/public/industry-insight-report/`，
  用户文档见 `docs/guide/industry-insight-report.md`。
- 日期：2026-11-20
- 目标：在 DeerFlow 上落地一条"产业 × 地区"产业发展状况报告的**批量、可校验、可断点续跑**的标准生成流水线，交付物为 `report.md` → `report.html`（分页、多图表）→ `report.pdf`。
- 样例基线：《上海市类脑智能 产业洞察报告》（19 页样张，封面/页眉页脚/评分/图谱/企业画像/创新/发展五大章）。

---

## 1. 需求拆解（对应流程步骤 1）

批量任务的原子单元是 **(地区, 产业, 数据截至日)** 三元组。每个原子任务固定产出同一套章节骨架（与样张对齐），差异仅来自数据与框架选择：

| 拆解层 | 内容 | 产出 |
| --- | --- | --- |
| 任务层 | 批量清单（manifest）：task_id、region(adcode)、industry、as_of、选项（是否联网取框架、是否出 PDF） | `manifest.json/csv` |
| 规格层 | 需求拆解：把"某地区某产业发展状况"拆为章节清单 + 每章数据需求 + 图表计划 | `spec.json` |
| 框架层 | 选择分析框架（内置库 + 可选联网调研），给出每章分析逻辑链 | `framework.json` |
| 数据层 | 按"章节→取数命令→字段"映射取数，落盘原始数据包 | `data/*.json` + `data_manifest.json` |
| 文稿层 | 模板化事实段 + LLM 分析段，合成 MD | `report.md` |
| 校验层 | 数据三层校验 + 文稿数字回溯校验 | `validation_report.json` |
| 渲染层 | 分页 HTML（封面/页眉页脚/图表/表格） | `report.html` + `charts/` |
| 检查层 | HTML 静态 + 无头浏览器度量检查 | `check_report.json` |
| 交付层 | PDF 转换 + PDF 校验 + 批量汇总 | `report.pdf`、`summary.json/md` |

## 2. 集成点与复用（为什么是 skill，而不是 core/extension）

按根 `AGENTS.md` 规则"业务逻辑不进 core；先评估扩展载体"。本需求是**交付型文档工作流 + 确定性脚本**，与现有 `cece-enterprise-risk-report`（报告型 skill 先例）同构，因此载体为**新建 public skill**：

```
skills/public/industry-insight-report/
├── SKILL.md                     # 工作流总控（阶段、门禁、断点续跑、交互原则）
├── references/
│   ├── prompts/                 # 中间 prompt 卡片 P0–P6（见 §7）
│   ├── frameworks/registry.json # 市场产业分析框架库（见 §4.2）
│   ├── frameworks/chains/*.json # 产业链模板（上/中/下游）
│   ├── hydc-command-map.md      # 章节→HYDC 命令→字段映射（口径以 live help 为准）
│   ├── report-structure.md      # 报告样例规范（见 §6）
│   ├── html-rules.md            # HTML 分页/图表/表格渲染标准规则（见 §5）
│   ├── chart-map.md             # 展示点→图表类型→组件参数映射（见 §5.3）
│   ├── validation-rules.md      # 数据校验规则清单（见 §4.4）
│   └── self-check-list.md       # 交付前自检清单
├── scripts/
│   ├── new_run.py               # 初始化 run 目录与 spec（S0）
│   ├── fetch_data.mjs           # 包装 cece-hydc-data 取数，落盘 data/*.json（S2）
│   ├── validate_data.py         # 三层数据校验 + 文稿数字回溯（S3.5）
│   ├── render_charts.py         # ECharts SSR → 内联 SVG（S4a）
│   ├── build_html.py            # 分页 HTML 组装（S4b）
│   ├── check_html.py            # 静态 lint + Playwright 度量（S4.5）
│   ├── make_pdf.py              # Playwright print-to-pdf + PDF 校验（S5）
│   ├── llm_client.py            # 批量模式直连 LLM（OpenAI 兼容，env 凭据）
│   └── batch_run.py             # 批量编排：并发/重试/断点/汇总（S6）
├── templates/                   # cover/header/footer/page/table/chart 主题模板
├── assets/                      # logo、geojson（按 adcode 缓存）、色板 tokens
└── tests → 仓库根 tests/skills/industry-insight-report/（离线单测）
```

复用的现有 skill（不重写）：

| 现有 skill | 在本流水线中的角色 |
| --- | --- |
| `cece-hydc-data` | 唯一业务事实数据来源；`fetch_data.mjs` 仅包装其脚本，凭据不落地 |
| `consulting-analysis` | 框架选择与"Visual Anchor → Data Contrast → Integrated Analysis"写作法的规范来源；本 skill 的 prompt 卡片继承其零幻觉与 GB/T 7714 规则 |
| `chart-visualization` (AntV) | 备选图表引擎：network/sankey/fishbone 等 ECharts 不擅长的图型 |
| `cece-enterprise-risk-report` | 工程先例：references 四件套、断点续跑、自检清单的组织方式 |

交互/单份报告走 **agent 驱动模式**（agent 按 SKILL.md 逐阶段执行）；批量走 **runner 驱动模式**（`batch_run.py` 直接执行确定性阶段，LLM 阶段用 prompt 卡片直连或提交 Gateway thread，二选一可配置，见 §3.3）。

## 3. 流程控制（状态机、门禁、断点）

### 3.1 阶段状态机

```
S0 初始化/需求拆解 ──> S1 框架选择 ──> S2 取数 ──> S3 文稿(MD) ──> S3.5 数据校验 ─┐
      ▲                                       │                        │fail(可修复)
      │                                       │fail                    ▼
      │                                       └──────────────────> 修复重试(≤2次)
S6 汇总 <── S5 PDF <── S4.5 HTML检查 <── S4 HTML渲染 <────────────── pass
                 │fail            │fail
                 └─ 降级/重试 ≤2 ──┘
```

- 每个阶段入口/出口有**文件契约**（§3.2），出口不满足即门禁失败。
- `progress.json` 记录每阶段 `status: pending|running|passed|failed|degraded`、尝试次数、时间戳、产物哈希；重跑跳过已 passed 阶段（断点续跑，先例同 `cece-enterprise-risk-report`）。
- 重试策略：每阶段最多 2 次自动修复重试；仍失败则按**降级路径**处理并在全局 summary 中标红：
  - 图表渲染失败 → 该展示点降级为表格（保留数据，注明"图表降级"）；
  - PDF 失败 → 交付 HTML + 失败原因，任务状态 `degraded`；
  - P0 数据缺失或校验不过 → 任务 `failed`，不产出 PDF（宁可缺任务不缺错数）。

### 3.2 run 目录契约（每个 task 一个目录）

```
runs/<task_id>/
├── manifest_entry.json  spec.json  framework.json  progress.json
├── data/            # 每个数据集一个 json：scores/chain/enterprises/patents/financing/parks...
├── data_manifest.json   # 每条数据：source 命令、取数时间、口径、as_of
├── validation_report.json
├── narrative/       # LLM 分析段分章落盘（可断点）
├── report.md
├── charts/          # chart_<id>.svg + charts.json（echarts option 存档，可复渲染）
├── report.html  check_report.json  report.pdf  pdf_check.json
└── logs/<stage>.log
```

### 3.3 批量编排（batch_run.py）

- 输入 `manifest.csv|json`：`task_id, region_adcode, region_name, industry, as_of, options...`
- 并发：信号量默认 3（可配），HYDC 调用遵守 `cece-hydc-data` 的配额规则（单任务取数命令数上限写进 fetch 包装层）。
- LLM 通道（批量模式可配置）：
  - **B2 直连（默认推荐）**：`llm_client.py` 读 operator 环境变量 `REPORT_LLM_BASE_URL / REPORT_LLM_API_KEY / REPORT_LLM_MODEL`（与 `HYDC_API_KEY` 同策略：不进 prompt、不进产物、不进日志），按 prompt 卡片调用，输出强制 JSON/MD schema 校验；
  - **B1 Gateway thread（可选）**：通过 Gateway `threads`/`assistants_compat` API 每任务起一个 agent run，复用 agent 工具与护栏；runner 轮询并回收产物。用于需要 web_search 等工具的复杂任务。
- 汇总：`summary.json/md`（成功/降级/失败、每阶段耗时、校验失败 Top 原因），失败任务支持 `--retry-failed` 单跑。
- 幂等：task_id = hash(region+industry+as_of+options)，重复提交跳过。

## 4. 各阶段设计（含中间 prompt 与校验）

### 4.1 S0 需求拆解（prompt P0/P1）

- P0（批量默认 deterministic）：由 `(region, industry, as_of)` 直接实例化标准章节骨架（§6），产出 `spec.json`：章节列表、每章数据需求（指标/类型/优先级 P0-P2/时间范围）、图表计划。
- P1（LLM，仅当用户给出非标问题或新产业）：把自然语言需求拆为同一 schema 的 `spec.json`；规则：不臆造指标，缺口径标 `unknown` 交校验层处置。

### 4.2 S1 分析框架调研与选择（prompt P2/P2b）

- **内置框架库** `references/frameworks/registry.json`（市场通用框架，含来源引用）：
  Porter 五力、PESTEL、价值链/产业链（上中下游）、波特钻石（区域竞争力）、产业生命周期、BCG/GE-McKinsey 组合、TAM-SAM-SOM、Gartner 技术成熟度、SWOT、**六维产业评分卡**（样张模型：产业规模/优质企业/创新能力/融资能力/产业效益/成长能力）、**专利价值三维模型**（技术稳定性/先进性/保护范围）。
  每条记录：`id, name, source, applies_to, required_data[], typical_charts[], reasoning_chain`。
- **产业链模板** `chains/<industry>.json`：上游/中游/下游环节树（样张即类脑智能链）；未知产业由 P2 起草、校验层检查环节完整性后缓存入库（入库走 PR，运行时不改库，保确定性）。
- **联网拉取（可选，批量默认关）**：P2b 用 web_search 检索咨询机构/信通院/赛迪/券商的该产业分析框架与指标体系，产出 `framework_notes.md`（含 URL 与拉取日期），只作选材参考，不直接进报告数字。
- P2 输出 `framework.json`：章节 → 框架 id → 分析逻辑链（观察→归因→含义）→ 所需数据引用（指向 spec 的数据需求编号）。选择原则继承 consulting-analysis：2–4 个互补框架、数据可得优先、显式映射。

### 4.3 S2 取数（deterministic）

- `hydc-command-map.md`：章节→命令→字段→单位映射（如 企业趋势→存量/新注册序列；区域分布→分区计数；专利→类型/价值/申请人/区域；融资→趋势/轮次/区域/事件/机构；载体→园区入驻）。口径以 `cece-hydc-data` live `help` 为准，映射文件仅作发现提示（沿用其规则）。
- `fetch_data.mjs`：按 spec 的 P0→P1→P2 顺序取数，"取够即停"；每个数据集落盘带 schema 头：`{dataset, as_of, source_cmd, fetched_at, unit, rows[]}`；空结果/报错记为**数据限制**写入 `data_manifest.json`，不视为"不存在"。

### 4.4 S3 文稿 MD + S3.5 数据校验（核心质量门）

- 文稿 = **模板事实段**（样张话术槽位化："截至 X，存量企业 N 家，较上年末增长 p%……"，数字只从数据包插值）+ **LLM 分析段**（prompt P3：每章按 What→Why→So What，只允许引用数据包数字与校验层登记的派生值；事实与推断分句；缺口明说）。
- `validate_data.py` 三层 + 文稿回溯：
  - L1 schema：每数据集 jsonschema（字段/类型/单位/日期范围）。
  - L2 一致性：分项和=总计（±容差）、占比和=100%（±0.5）、TopN 单调不增、子集≤全集（如分区企业数合计≤存量企业数；专利四类型合计=专利总数）、单位归一（万元/亿元统一存元+展示单位）、日期≤as_of。
  - L3 文稿回溯：正则抽取 `report.md` 全部数字与百分比，逐一匹配数据包值或**派生值白名单**（校验器自己算的占比/增速/CAGR）；未匹配即 failure（防幻觉硬门）。
- 输出 `validation_report.json {passed, checks[], failures[{level, dataset, rule, detail}]}`；门禁：L1/L2 的 P0 失败或任何 L3 失败 → 阻断；自动修复路径：重取数(1 次)→重写文稿(1 次)→failed。

### 4.5 S4 HTML 渲染（标准规则见 references/html-rules.md）

- **分页模型**：A4 210×297mm，页边距上 18mm/下 16mm/左右 16mm；每页一个固定尺寸 `.page` 容器（内容盒高度恒定），渲染器做**块打包**：按预估高度（图表固定高、表格按行数、文本按字数/行宽估算）把 block 序列装箱到页，超箱即换页；`.page { page-break-after: always }` + `@page { size: A4; margin: 0 }`，页眉/页脚/页码作为每页重复 DOM（不依赖 running elements，保证 Chromium 打印稳定）。
- **封面/封底**：封面=logo+平台名+报告名+地区产业+章节导航条+生成日期与免责句；封底=logo+网址+机构联系方式（样张一致）；封面封底无页眉页脚。
- **图表**：ECharts 5 **SSR 输出 SVG 字符串内联**（`echarts.init(null, null, {renderer:'svg', ssr:true})`），HTML 单文件自包含、打印无需 JS；`charts.json` 存档 option 便于复渲染与审计。地图用 assets/geo/<adcode>.json（DataV GeoAtlas 一次性缓存入库；缺 geojson 时降级为横向条形图并注明）。
- **表格**：渲染器按页高切行，跨页重复 `<thead>`；数字右对齐、千分位英文逗号、单位进表头或表注；Top10 长文本列（如投资机构）限宽换行，单行单元格最大高度超限则截断+附录全文。
- **样式 tokens**：色板（样张蓝系 + 辅色绿/橙，打印友好、色盲可辨）、字体栈（中文思源黑体/系统回退）、标题层级色（章=品牌蓝）、强调数字色（蓝=事实强调、红=风险/异动，与样张一致）。

### 4.6 S4.5 HTML 检查（check_html.py）

- 静态 lint：单文件自包含（无外链 css/js/img）、`</html>` 存在、必需块齐全（封面/页眉/页脚/页码/各章）、svg 数量=charts.json 数量且非空、id 唯一、无 `NaN/undefined/None` 文本泄漏。
- 无头度量（Playwright Chromium）：每个 `.page` 的 `scrollHeight ≤ 内容盒高度`（溢出列表为空）、图表 svg 尺寸在页内、表格未被截断在单元格中间；首末页截图存档供人工抽检。
- 失败→自动修复 1 次（重装箱/降级图表）→复检；仍失败任务 failed。

### 4.7 S5 PDF（make_pdf.py）

- 主路径：Playwright Chromium `page.pdf(format='A4', print_background=True, prefer_css_page_size=True)`；中文字体随环境（镜像内置 Noto Sans CJK）。
- 校验 `pdf_check.json`：页数 == `.page` 数；pypdf 抽取第 2 页文本含页眉"产业洞察报告"与页码；文件尺寸>阈值；封面页抽取含报告标题。
- 回退：WeasyPrint（HTML 为静态 SVG，无 JS 依赖，可渲染）；两路皆败→降级交付 HTML。

### 4.8 S6 汇总

`summary.md/json`：任务级状态、阶段耗时、校验失败原因分布、降级清单；批量报告本身也用本流水线渲染（dogfooding）。

## 5. 展示点 → 图表映射（chart-map.md 摘要）

| 展示点（样张） | 图表 | 引擎 | 优化规则 |
| --- | --- | --- | --- |
| 综合评分+等级 | 分段等级条(gauge/custom)+排名卡 | ECharts | 等级阈值固定五段 |
| 六维评分 | 雷达图 | ECharts | 轴标签带分值 |
| 产业链 | 树图(横向 tree) 上/中/下游三块 | ECharts tree | 节点超长省略+title 全量 |
| 企业趋势 | 分组柱(存量/新注册) | ECharts | 双系列异量级时改双轴 |
| 企业结构 | 金字塔(funnel 反向) | ECharts | 层标签=家数+占比 |
| 注册资本/年限/轮次/融资类型 | 环图(donut) | ECharts | >8 类合并"其他" |
| 区域分布 | 分区 choropleth 地图 + Top10 表 | ECharts map | 缺 geojson 降级条形 |
| 专利趋势 | 堆叠柱(四类型) | ECharts | 图例置底 |
| 专利价值分项 | 气泡矩阵(scatter symbolSize) | ECharts | 气泡面积∝件数 |
| 融资趋势 | 柱+线双轴(金额/件数) | ECharts | 左右轴单位标注 |
| 融资区域/关键技术/申请人 | 横向条形 Top10 | ECharts | 降序、值标签外置 |
| 财务指数 | 双线图(总/平均) | ECharts | 基线 100 参考线 |
| 网络/流向类（扩展） | network/sankey | chart-visualization(AntV) | 仅交互版 HTML 使用 |

## 6. 报告样例规范（report-structure.md 摘要，样张 + 增强）

1. **封面**：logo/平台名、报告名"产业洞察报告"、`<地区><产业>`、五章导航、生成日期+免责句；增强：报告编号与版本号、数据截至日。
2. **页眉**：左 logo+平台名，右"产业洞察报告"；**页脚**：居中页码（正文起编 1）。
3. **执行摘要**（新增，1 页）：评分结论 + 3–5 条关键发现 + 数据范围一句话。
4. **正文五章**（与样张同）：一 产业评分／二 产业图谱／三 企业画像（趋势/结构/注册资本/年限/区域/龙头）／四 产业创新（专利趋势/价值/关键技术/区域/申请人）／五 产业发展（财务/投融资/载体）。
5. **每图每表必带数据范围块**：`截至：YYYY-MM-DD　数据来源：<source>`（样张已有，强制）。
6. **方法论与数据口径**（新增章）：评分模型、专利价值模型、企业价值模型说明（样张散落脚注，集中成章）+ 数据限制声明。
7. **结论与建议**（新增章）：仅由校验过数据支撑的条件式建议。
8. **附录**（新增）：A 指标定义；B 全量数据表（Top10 之外的完整表）；C 图表索引。
9. **封底**：logo、网址、机构地址/邮箱（样张一致）。
10. **表格规范**：跨页重复表头；数值右对齐千分位；单位入表头；表题居中置于表上；来源注置于表下。
11. **分析推理规范**：每小节"观察→归因→含义"三段；事实句与推断句分离；推断须标注依据或列为假设；禁止无源数字（L3 门）。

## 7. 中间 prompt 卡片清单（references/prompts/）

| 卡片 | 阶段 | 输入 | 输出 | 关键约束 |
| --- | --- | --- | --- | --- |
| P0 需求实例化 | S0 | region/industry/as_of | spec.json | 标准骨架直接实例化 |
| P1 需求拆解 | S0 | 自然语言需求 | spec.json | 不臆造指标 |
| P2 框架选择 | S1 | spec + registry | framework.json | 2–4 互补框架、数据可得 |
| P2b 框架联网调研 | S1(可选) | industry | framework_notes.md | 带 URL/日期，不进数字 |
| P3 章节分析段 | S3 | 数据包+framework+章模板 | narrative/chN.md | 零幻觉、What-Why-SoWhat、事实推断分离 |
| P4 摘要/结论 | S3 | 校验后关键数字 | 摘要/结论段 | 条件式建议 |
| P5 自检改写 | S3.5 失败修复 | failures+原稿 | 修订稿 | 仅修复失败项 |

## 8. 测试与验收

- `tests/skills/industry-insight-report/`（离线）：fixture 用样张数字构造数据包；validate_data 的正/反例（注入不一致必失败）；build_html 装箱黄金测试（页数/svg 数/表头重复）；check_html 用 mock 度量；fetch/llm 传输层 mock；脚本 CLI 失败退出非零。
- E2E（带 marker，需 HYDC/Chromium）：1 个任务全链路出 PDF；3 任务批量含 1 个注入失败任务验证降级与汇总。
- 验收标准：校验门 100% 执行；L3 未匹配数字=0；HTML 溢出块=0；PDF 页数=HTML 页数；批量 summary 与 run 目录一致。

## 9. 里程碑与工作量（估）

| 里程碑 | 内容 | 估时 |
| --- | --- | --- |
| M1 | skill 骨架、spec/契约、manifest、batch 框架、P0/P1 | 0.5 周 |
| M2 | fetch 映射、validate_data、MD 生成与 L3 门 | 1 周 |
| M3 | ECharts SSR、build_html 分页、check_html | 1 周 |
| M4 | make_pdf、批量汇总、docs/guide 用户文档、测试补齐 | 0.5 周 |

## 10. 风险与开放问题（需评审确认）

1. **数据源边界**：仅 HYDC，还是允许公网检索补充（政策/新闻）？默认仅 HYDC（与 cece 策略一致）。
2. **品牌资产**：新华社/行业洞察 logo、封底联系方式是否可直接内置 assets？需授权确认，否则用占位 logo。
3. **批量 LLM 通道**：默认 B2 直连（需 operator 配 env 凭据）还是统一 B1 Gateway thread？
4. **PDF 环境**：部署镜像是否接受内置 Chromium + Noto CJK（config.example 已把 playwright chromium 列为可选 extra）？
5. **地区粒度**：仅直辖市/省，还是含地级市/区县（影响 geojson 与命令映射规模）？
6. **批量规模**：日产量与并发预期（决定 runner 并发与 HYDC 配额排队策略）。
7. **联网框架调研**：批量默认关闭是否可接受？
