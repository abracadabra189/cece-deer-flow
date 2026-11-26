# 本地 CECE MCP 取数映射（默认数据源）

本地启动的 CECE MCP 服务（FastMCP / Streamable HTTP，源码 `D:\project\毅达投资MCP\参考实现\entity_MCP`）：

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| NER | `http://127.0.0.1:18906/cece-mcp-servers/NER/stream` | 产业名 → industry_code / 体系 |
| enterprise | `http://127.0.0.1:18907/cece-mcp-servers/enterprise/stream` | 企业评分榜（find_companies） |
| industry | `http://127.0.0.1:18908/cece-mcp-servers/industry/stream` | 评分/画像/链条/创新/融资 |
| PEVC | `http://127.0.0.1:18910/cece-mcp-servers/PEVC/stream` | 创投补充（可选） |
| person | `http://127.0.0.1:18911/cece-mcp-servers/person/stream` | 人物（本流水线不用） |

启动：`start_servers.bat` 或逐个 `python servers/<x>_server.py`（依赖 mcp<2 / httpx / aiomysql / uvicorn / starlette）。
Gateway 配置：根 `extensions_config.json` 的 `mcpServers`（NER/enterprise/industry/PEVC/person）。

### 产业解析（多体系）

`search_industry_by_name` 按 **SELECTED → CSF → NSEI → GB → DE** 顺序尝试；取同层最匹配节点为主节点，
同层同关键词兄弟节点并入企业/融资查询（如"摩托车"仅存在于 CSF：3709 整车 + 3710 零部件，根类目 37）。
解析结果写入 `raw_mcp/manifest.json`（industry_code/industry_type/industry_codes）。
`SELECTED` 无节点不等于产业不存在，禁止据此断言"无数据"。

## 工具 → 数据集映射（fetch_data_mcp.py）

| 数据集 | 工具 | 关键出参 |
| --- | --- | --- |
| score | `get_industry_evaluation` | `score_dimensions[]`（维度/等级/分数/全国排名/全国同业数/地区排名/地区同业数） |
| chain | `get_industry_chain_tree` | `tree.children[]`（chain_sequence 1/2/3 = 上/中/下游；children 为环节与叶节点） |
| ent_trend | `get_industry_company_portrait --scale_months 24` | `scale_trend_stock/scale_trend_increment[]`（月/年 + scale_items） |
| ent_capital / ent_age | `get_industry_company_portrait` | `capital_distribution` / `age_distribution`（name/count/ratio） |
| ent_region | `get_industry_company_portrait` | `region_distribution[]`（region_name/company_count） |
| parks | `get_industry_company_portrait` | `park_distribution[]`（park_name/park_class/company_count/park_total_company_count） |
| patent_summary | `get_industry_innovation` | 专利总数/专利授权数/专利类型分布 |
| fin_summary / fin_type / fin_region | `get_industry_financing_overview` | event_count / by_financing_type(share 为小数) / by_region(amount 万元) |
| fin_trend | `get_industry_financing_trend` | yearly_trend[]（amount 万元 → 亿元） |
| fin_events | `get_industry_financing_events --financing_type 创投融资` | events[]（financiers/investors/amount/round/date） |
| fin_inst | `get_industry_investors` | investors[]（investor_name/event_count/invest_amount） |
| ent_top | `find_companies --sort_by 综合评分 --sort_order 降序` | items[]（companyName/registeredCapital/regionInfo/scoreInfo.valueScore） |

入口解析：产业名为中文时先 `search_industry_by_name --keyword <名> --industry_type SELECTED`，优先取 `行业编码 == 根类目` 的节点。

## 平台口径边界（登记 limitation）

- `ent_structure`：`type_distribution` 的 name 为 null（出参整形丢失类型名），无法映射上市/专精特新/高新；
- `fin_index`：`get_industry_listed_financial` 当前版本内部报错（slice(-20, None)）；
- `patent_trend/patent_value/patent_tech/patent_region/patent_applicant`：创新工具仅给累计计数与类型分布；
- `fin_round`：融资事件接口按单类型分页，不直出轮次分布（可用 events 明细近似，未启用）。

## 校验适配

- 专利类型合计 ≠ 专利总数（口径不同）→ 以 `parts_complete=false` 跳过 parts_sum；
- 融资 `share` 为小数（0.069）→ 归一化 ×100；
- 年度 `period`（"2016"）在取数事实段写作"较上年"。