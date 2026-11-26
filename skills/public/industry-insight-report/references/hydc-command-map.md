# HYDC 取数命令映射（真实命令体系，2026-11-23 校准）

> 命令与字段以 `cece-hydc-data` live `help` 为准；本文件为当前校准口径。凭据不落地（`HYDC_API_KEY` env）。

## 每报告 3 次调用（fetch_data.mjs）

| # | 命令 | 产物 | 用途 |
| --- | --- | --- | --- |
| 1 | `economicData queryIndustries --keyword <产业名> --format json` | `raw/industries.json` | 产业节点定位；中文入参解析 industryCode（优先根节点，如类脑智能=`XHICC011005`） |
| 2 | `economicData queryIndustryProfile --regionCode <R> --industryCode <I> --format json --all true` | `raw/profile.json` | 区域×产业聚合画像（groups: score/portrait/ip/finance/invest/report） |
| 3 | `economicData queryParkProfile --regionCode <R> --format json` | `raw/parks.json` | 区域园区（产业载体章） |

归一化由 `normalize_data.py` 完成：`raw/ → data/*.json`（报告 schema）+ limitations 登记。

## groups → 数据集映射

| 数据集 | 来源路径 |
| --- | --- |
| score | groups.score.evaluateResult（OVERALL→total/grade/rank；其余 itemList→dims） |
| chain | groups.portrait.industryDistribution.itemList（层→children→leaves，含 companyCount） |
| ent_trend | groups.portrait.scaleChartBundle.stockItemList/incrItemList（**月度粒度**，period 字段） |
| ent_structure | groups.portrait.typeDistribution.itemList（全部企业/A股上市/专精特新/高新技术；缺项=None） |
| ent_capital / ent_age | groups.portrait.pieChartBundle.capitalItemList/ageItemList（占比按总量重算；覆盖不足补"其他/未分档"） |
| ent_region | groups.portrait.regionDistribution.itemList（listed/srme/hightech 平台不直出→"—"） |
| patent_summary / patent_trend | groups.ip.patent.count + groups.portrait.patentStat（年度×类型；parts_complete 标记口径闭合） |
| fin_index | groups.finance.allCompanyOperationTrend / allCompanyAssetTrend（总营收/总资产水平指数，2020=100） |
| fin_trend / fin_summary | groups.invest.financeTrend（万元→亿元换算；无效年份过滤）+ regionFinance.num（累计次数） |
| fin_type | groups.invest.typeFinance.data（事件数口径；无金额字段） |
| fin_region | groups.invest.regionFinance.detail（区县 num/amount） |
| parks | groups.list/region（queryParkProfile，字段名防御式提取） |

## 平台口径边界（登记为 limitation，章节优雅跳过）

`ent_top、patent_value、patent_tech、patent_region、patent_applicant、fin_round、fin_events、fin_inst`
——聚合画像精选子集不直出（无企业级评分榜、专利价值分布/技术/申请人/区域 Top、轮次/逐笔事件/机构字段）。
其他边界：三层与分项不可加总；评分为平台模型口径非市场份额；财务指数为 2020=100 水平指数；空结果≠无数据。

## 校验适配

- 精选子集占比和 <99.5% 时跳过 shares_sum 门（normalize 已对可闭合分档补"其他"档）；
- 附录图表索引的图号序列经 `--max-seq` 豁免 L3 回溯；
- 月度期间（YYYY-MM）在 L3 预清洗中按日期剔除。
