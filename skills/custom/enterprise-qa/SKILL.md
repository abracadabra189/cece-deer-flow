---
name: enterprise-qa
description: Use when the user requests factual Chinese enterprise, person, industry, region, fund, financing, investment, tender, shareholder, or management lookups, including condition-based lists. Do not use for a full enterprise portrait, development outlook, corporate report, due diligence, strategic assessment, or multi-dimensional competitiveness analysis.
---

# 企业问数

本 Skill 用于企业信息、融资信息、产业基金和企业关系查询。所有事实必须来自已配置的 MCP 工具，不要凭模型记忆补充企业数据。

## 总体规则

1. 先判断问题属于企业查询、人物查询、产业/区域查询，还是融资/基金查询。
2. 用户提供企业简称、品牌名或模糊名称时，必须先调用 `entity_resolve` MCP 的 `search_enterprise_by_name`。
3. 企业 MCP 只使用 NER 返回的工商登记全称；不要猜测企业全称，也不要直接把简称传给企业查询工具。
4. 如果企业实体未匹配，使用用户原始名称重新调用一次 `search_enterprise_by_name`；最多重试一次。
5. 如果工具返回“查询无数据”“参数不合法”“无权限”或“调用失败”，如实说明，不要把它改写成实体未匹配。
6. 用户没有要求长报告时，只调用完成问题所需的最少工具，并用中文简洁回答。
7. 工具返回的原始 JSON 不要整段展示给用户；提取字段、单位、日期和状态后再组织答案。
8. 对融资、工商和人员数据注明数据返回时间或工具提供的更新时间；工具没有时间时，不自行编造日期。

## 企业问题调用顺序

对于“介绍某公司”“注册资本”“法人”“经营范围”“股东”“高管”“融资”“对外投资”“招投标”等问题：

```text
用户企业名称
  -> entity_resolve.search_enterprise_by_name
  -> 工商登记全称/companyId
  -> enterprise MCP 对应查询工具
  -> 中文结构化回答
```

常用企业工具包括：

- `get_enterprise_basic`：企业基本工商信息
- `get_enterprise_tags`：企业标签、资质、荣誉和风险
- `get_enterprise_shareholders`：股东信息
- `get_enterprise_management`：主要人员、董监高和任职信息
- `get_enterprise_VCPE_financing`：创投/股权融资
- `get_enterprise_stock_financing`：股票融资
- `get_enterprise_bank_financing`：银行借款
- `get_enterprise_outbound_investment`：对外投资
- `get_company_graphy`：企业关系图谱
- `get_businessFinance_graphy`：融资关系图谱
- `get_query_winTenderer_tenderee`：中标/招标信息

如果一个问题需要多个企业工具，先完成实体解析，再并行或连续调用对应查询工具。回答中区分“没有数据”和“查询失败”。

## 产业、区域和融资问题

- 用户使用自然语言产业名称，而 PEVC 工具需要产业代码时，先调用 `entity_resolve.get_industry_tree`。
- 用户使用自然语言区域名称，而工具需要标准区域时，先调用 `entity_resolve.get_region_tree`。
- “最近有哪些企业融资”“某产业有哪些获投企业”使用 `pevc.search_financing_companies`。
- “某地区有哪些产业基金”使用 `pevc.get_industryFund_list`。
- “某基金投了哪些企业”先用 `pevc.get_fund_detail_basic` 确认基金，再调用投资明细工具。
- “某企业和竞品融资差异”先完成企业实体解析，再使用 `pevc.get_query_competitive_Finance`。
- 日期参数统一使用 `yyyy-MM-dd`；用户只给“最近”“今年”等模糊时间时，先按当前日期推导明确区间，并在回答中说明查询区间。

## 回答格式

企业单体查询优先使用：

```markdown
## 企业名称（工商登记全称）

### 基本信息
- ...

### 查询结果
- ...

### 数据说明
- 来源：企业 MCP / NER / PEVC
- 查询状态：查询成功 / 查询无数据 / 实体未匹配 / 调用失败
```

列表查询优先使用表格，金额保留工具返回的币种和单位，不进行未经依据的换算。对于多个候选企业，先列出候选工商全称和 companyId，请用户确认后再查询企业详情。
