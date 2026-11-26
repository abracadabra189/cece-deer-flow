# 中间 Prompt 卡片（P0–P5）

通用禁令：零幻觉（数字只来自数据包/派生值）；事实与推断分句；缺口径写"数据暂缺"；输出语言 zh_CN；数字千分位英文逗号。

## P0 需求实例化（S0，默认 deterministic，无需 LLM）
输入：region_code/industry_code/as_of。输出：`spec.json`（章节骨架+数据需求+图表计划，见 report-structure.md §1）。规则：标准骨架直接实例化；不做自由发挥。

## P1 需求拆解（S0，仅非标需求）
输入：自然语言需求。输出：同 spec.json schema。规则：不臆造指标；缺口径标 `unknown` 交校验层；章节必须映射到标准数据集 id。

## P2 框架选择（S1）
输入：spec.json + registry.json（category 匹配结果）。输出：`framework.json {category, combo, chapters:[{id, frameworks[], reasoning_chain[], data_refs[]}], downgrades[]}`。
规则：2–4 个互补框架；数据可得优先（required_data 的 P0 缺失即降级并记录）；显式章→框架映射；组合框架按 combination_rules.members 展开。

## P2b 框架联网调研（S1，仅 --public-web true）
输入：industry 名 + category。动作：web_search 检索信通院/赛迪/券商/咨询机构该产业分析框架与指标体系。输出：`framework_notes.md`（每条含 URL+拉取日期+要点）。规则：只作选材参考；任何数字不得进入报告；批量/默认关闭。

## P3 章节分析段（S3）
输入：章节数据包 + framework.reasoning_chain + 模板事实段。输出：`narrative/ch<N>.md`（每节 What→Why→So What 三段）。
规则：只引用数据包数字与派生值；归因须标注依据或列为假设；So What 为条件式；每节末可选一句 blockquote 结论；禁止无源因果与心理化表述。

## P4 摘要与结论（S3）
输入：校验后关键数字清单。输出：执行摘要（3–5 条关键发现）+ 结论章（ flowing prose，无 bullet）。规则：每条发现=事实数字+含义；结论不含新数字。

## P5 失败修复改写（S3.5 失败后）
输入：validation failures + 原稿。输出：修订稿。规则：仅修复失败项对应句子；不得改动已通过数字；修复后重跑 L3。

## 无 LLM 回退（默认离线/批量无凭据）
分析段由规则化模板生成：观察=Top 项+占比+趋势方向句；归因="结构上集中于<环节/区域>，与<数据集>分布一致（描述性，非因果）"；含义=条件句模板。保证全链路离线可跑且 L3 必过。
