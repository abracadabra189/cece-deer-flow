# 数据校验规则（validate_data.py）

输出 `validation_report.json {passed, checks[], failures[{level, dataset, rule, detail}]}`；退出码 0=pass，1=fail。

## L1 schema（每数据集）
- 必备头字段：`dataset, as_of, source_cmd, fetched_at, unit, rows[]`；
- 字段类型/枚举/取值范围按数据集声明（如 score.total ∈ [0,100]；占比 ∈ [0,100]；日期 ≤ as_of）。

## L2 一致性
| 规则 | 适用 | 说明 |
| --- | --- | --- |
| parts_sum | patent_trend, fin_type, ent_capital, ent_age | 分项和 = 总计（±0.5 或 ±0.5%） |
| shares_sum | 所有含 share 字段的数据集 | 占比和 = 100 ± 0.5 |
| monotonic_desc | 所有 TopN 数据集 | 排序键单调不增 |
| subset_le | ent_region vs ent_trend 末值；patent_region vs patent 总数 | 子集合计 ≤ 全集 |
| date_le_asof | 所有日期字段 | ≤ as_of |
| unit_norm | 金额字段 | 存 `{value_yuan, display_unit}` 双字段，display 与 value 换算一致 |
| rank_unique | TopN | 排名 1..N 无重复 |

## L3 文稿数字回溯（防幻觉硬门）
- 正则抽取 `report.md` 中全部数字/百分比/金额 token；
- 白名单 = 数据包全部数值 ∪ 校验器派生值（占比、同比/环比增速、CAGR、合计），按展示格式生成变体（原值、2 位小数、百分 2 位、千分位、万元/亿元换算）；
- 任一 token 未命中 → failure(level=L3)；
- 允许豁免清单：年份、排名序号、章节号、模型满分（100/10）、等级阈值，写在 `validation-rules` 常量中。

## 门禁与修复
- 阻断：L1/L2 中 P0 数据集失败、任何 L3 失败；
- 自动修复 ≤2 次：①重取数 ②重写文稿（P5 卡片）；仍失败任务 failed；
- 非 P0 数据集缺失：登记 `data_manifest.json.limitations`，报告方法论章声明，不阻断。
