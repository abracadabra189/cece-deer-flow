# hydc 命令映射（报告取数口径）

> 所有取数经 `cece-hydc-data` 的 `hydc.mjs` wrapper。本表确保报告与取数工具口径一致。
> 通用调用：`node /mnt/skills/public/cece-hydc-data/scripts/hydc.mjs query "<命令>"`
> companyId 由 queryCompanyID（按简称模糊查）或 advanceSearchCompany 返回的 `company_id` 取得。

## 步骤 → 命令 → 取数

### 1. 新注册企业（当月、某区域）
```
economicData advanceSearchCompany --regionCode <区划码> --ageIn PAST_ONE_MONTH --format json
```
- 区划码先用 `economicData queryRegion --keyword <区域名>` 取得（返回6位区划码）
- 按行业筛：加 `--companyScopeIn COMPANY_SCOPE --companyKeyword 人工智能`（经营范围匹配；**勿用 industryKeyword**，匹配面太窄）

### 2. 企业风险 / 舆情事件
```
economicData queryCompanyEvents --companyId <id> --event 2,4 --startDate <起> --endDate <止> --format json
```
- event：1 商机 / 2 通用风险 / 3 银行风险 / 4 舆情
- 返回：事件类型/摘要/情绪/重要度/来源/链接

### 3. 股东结构 / 投融资 / 图谱布局
```
economicData queryCompanyProfile --companyId <id> --category basic,invest,graph
```
- basic=基本信息+股东，invest=投融资，graph=图谱

### 4. 行业资讯 / 舆情背景
```
news queryElasticInfo --category 9 --keyword <行业关键词>
```

## 说明

- 本表为当前取数口径；**具体命令与字段以取数工具 `help` 查询的当前 schema 为准**，工具调整后按 help 结果更新。
- 企业集合 >200 家：默认聚合画像（分批取统计），不逐家展开；用户要逐家深度时按批次分片取数（断点续跑）
- 按需取数、取够即停
