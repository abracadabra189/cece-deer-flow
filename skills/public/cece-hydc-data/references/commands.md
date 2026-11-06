# 行业洞察数据（HYDC）命令清单快照

> 快照时间：2026-10-28，来源：各工具 `help` 实时返回。
> 命令名与参数若有变化，一律以 `help --name <命令名>` 的实时返回为准，不要依赖本快照里的描述细节。

## 分层帮助用法（先 help 后 query）

| 动作 | 命令 |
|---|---|
| 工具总览 | `help` |
| 某工具全部命令 | `<工具名> help`，如 `economicData help` |
| 单命令参数与返回结构 | `<工具名> help --name <functionName>`（别名 `--command`） |
| 行情接口与字段 | `marketData list-interfaces`；`marketData fields --command <接口名>` |
| 行内帮助 | `<工具名> <functionName> --help` |

命令统一形如 `<工具名> <functionName> [--参数 值]`。

---

## economicData（42）—— 宏观 / 行业 / 县域 / 企业 / 财务

- `querySecuMain`：按证券代码/简称/拼音简称模糊查询上市公司基本信息
- `loadChinaMacroCategory`：中国宏观数据库一级指标分类（根节点）
- `queryChinaMacroSubCategory`：中国宏观指标子分类信息
- `queryChinaMacroIndictorValue`：中国宏观指标信息
- `loadGlobalMacroCategory`：全球宏观数据库一级指标分类（根节点）
- `queryGlobalMacroSubCategory`：全球宏观指标子分类信息
- `queryGlobalMacroIndictorValue`：全球宏观指标数据
- `loadIndustryCategory`：行业经济数据库一级指标分类（根节点）
- `queryIndustrySubCategory`：行业经济指标子分类信息
- `queryIndustryIndictorValue`：行业经济指标数据
- `queryCountry` / `queryTop100Country` / `queryCountryIndicator` / `queryCountryIndicatorValue` / `queryTop100CountryIndicatorValue` / `queryCountryChartData` / `queryTradeData`：国别/贸易相关
- `queryCompanyBasicInfo`：根据公司 code 查询上市公司基本信息
- `queryEquityChangesStatement`：所有者权益变动表（单期）
- `queryBalanceSheet`：资产负债表 + 附注
- `queryIncomeStatement`：利润分配表（利润表）+ 附注
- `queryQIncomeStatement`：单季利润表
- `queryCashFlowStatement`：现金流量表
- `queryQCashFlowStatement`：单季现金流量表
- `queryFinancialDerivative`：财务衍生指标（杜邦分析）
- `queryFinancialTTMDerivative`：财务 TTM 衍生指标（杜邦分析）
- `queryTradingCapitalFlow`：上市公司和所在行业资金净流入
- `queryCompanyID`：按企业简称模糊查询企业 ID/code/名称（覆盖企业库全部企业，非仅上市公司）
- `queryCompanyProfile`：按企业 ID 取企业全景画像（基本/经营/知产/资质/榜单/财务/投融资/司法风险/经营风险/图谱评分）
- `queryRegion`：按关键词查区划（regionCode，省-市-县三级）
- `queryRegionProfile`：按 regionCode（或名称）+year 聚合区域画像（GDP/财政/债务/企业/专利/科创/五年规划/园区/融资）
- `queryIndustries`：产业列表（关键词模糊搜索/全量目录）
- `queryIndustryProfile`：regionCode+industryCode 聚合区域行业画像（知产+研报+图表，输出 LLM 友好 Markdown + 结构化 groups）
- `advanceSearchCompany`：按产业关键词/区划码/企业关键词/规模等条件筛选企业列表
- `queryParks`：按省/市/区划码/关键词查园区，返回 parkId
- `queryParkProfile`：双模式——parkId 查园区详情/子园区/入园企业/产业分布/企业特征；仅 province/regionCode 则查区域园区列表与分布
- `queryPersons`：按姓名模糊查询人物，返回 personNo
- `queryPersonProfile`：按 personNo 查人物全景（概述/任职持股/集团关联）
- `queryTalents`：关键词搜索人才列表，返回 talentId
- `queryTalentProfile`：按 talentId 查基本信息/区域排名/研究关键词/学术成果/专利/任职流动
- `queryGroupId`：按关键词模糊搜索集团 ID
- `queryGroupProfile`：按集团 groupId 查集团画像（详情/成员企业/分类计数/融资/产业/资质图谱/风险商机）

---

## marketData（11）—— 行情 / 分时 / K线 / 大宗 / 外汇

- `real_trend`：实时分时（当天数据，含涨跌家数等字段）
- `list`：市场（交易所）列表，输出 finance_mic / finance_name
- `summary`：市场概要信息
- `real`：行情报价（开盘价/最新价/流通市值/换手率/每股收益等）
- `trend`：分时信息
- `kline`：K线
- `wizard`：按关键字查股票代码
- `list-interfaces`：列出所有可用行情接口
- `fields`：查询可用 fields 参数说明
- `queryTrendCount`：市场交易分钟数
- `queryOTC`：伦敦黄金白银现货实时行情

---

## news（10）—— 资讯 / 公告 / 研报 / 招投标

- `queryElasticInfo`：查询行业资讯
- `queryXhcjInfo`：中国金融信息网（新华财经）资讯
- `queryLiveInfo`：华尔街见闻最新快讯 / 关键词搜索
- `queryDigitInfo`：数字经济相关资讯（向量搜索）
- `queryBidiInfo`：招投标信息
- `queryMysteelInfo`：Mysteel 相关
- `queryReportInfo`：各券商最新研究报告
- `queryShujujuReport`：数据局网站（shujuju.cn）研究报告，按标题关键词查询
- `advanceSearchReport`：queryReportInfo 升级版，Elasticsearch 搜索，按关键词/栏目/发布主体/时间区间
- `advanceSearchAnnouncement`：按关键词/时间区间查 A股/新三板/港股公告，以及债券/基金公告

---

## chartData（6）—— ECharts 图表渲染参数

- `queryCountryChartParams`：国别图表参数
- `queryChartParams`：通用图表参数
- `queryIndusryChartParams`：按 indicatorCode 取行业经济图表渲染参数
- `queryGlobalMacroChartParams`：按 indicatorCode 取全球宏观图表渲染参数
- `queryChinaMacroChartParams`：按 indicatorCode 取中国宏观图表渲染参数
- `queryTrendChartParams`：按行情代码取行情图表参数（K线/实时行情）

---

## querySkill（组合场景，动态）

多工具组合场景用 `querySkill` 获取调用指引，**列表随对话反馈迭代，不做静态快照**：

- `querySkill help`：返回可用 Skill 精简列表，判断适用场景。
- `querySkill help --name <skillName>`：返回该场景 Skill 的详细调用步骤与命令组合（如 `china-marco-rmb`、`global-commodities-analysis`、`steel-analysis`、`region-economy-query`、`stock-financial-statement-analysis`、`bidding-info-query` 等）。
- 组合场景 Skill 带版本号（如 `region-industry-enterprise-list-v3.7`），优先使用高版本。

---

## 口径与边界提示

- 底层命令共 69 个（42/11/10/6）；对外答复须标注来源，避免幻觉（news 类尤甚）。
- `querySkill` 技能数、命令清单以实时 `help` 为准，本快照仅作发现命令的入口，参数细节务必查 `help --name`。
