---
name: cecemate-early-stage-project-weekly
catalog_category: business_scenario
reference_cases: []
starter_prompt: 请生成最近一周早期科技项目投资周报，整理融资事件、重点项目与待核实信息。
starter_references: []
display_description: display_description_cecemate-early-stage-project-weekly_ABC
example_queries:
  - cecemate-early-stage-project-weekly_query1
  - cecemate-early-stage-project-weekly_query2
  - cecemate-early-stage-project-weekly_query3
icon_path: /images/skills/early-stage-project-weekly.svg
display_name: 早期项目投资周报
description: 当用户需要生成天使轮、Pre-A、A 或 A+ 轮融资的早期科技项目投资周报、早期融资盘点或一级市场早期项目监测报告时使用。
---

# 早期项目投资周报

生成基于 CeCe MCP 数据的单期早期科技项目融资 HTML 周报，供投资团队内部研究与跟踪使用。

## 数据与事实边界

- 业务事实仅来自当前会话可用的 CeCe MCP：NER、PEVC、enterprise、person。
- 每次首次使用某个 MCP 服务时，先阅读模型可见的工具描述，确认工具名、必填参数、分页规则和返回字段；`references/mcp-playbook.md` 是调用意图与历史映射，不替代实时契约。
- 不把未披露金额显示为零，不猜测投资方、创始人、实控人或持股比例。
- 正文不出现 MCP、工具名、接口参数、内部字段名或取数过程。

## 默认口径

- 周期：用户未指定时，使用上一完整自然周（周一至周日）；周次使用日期库的 ISO 周编号计算，不手工估算。用户指定日期区间时按其要求。
- 轮次：天使轮、Pre-A 轮、A 轮、A+ 轮；种子轮仅在用户明确要求时纳入。
- 范围：默认全国；用户可指定区域或产业。
- 交付：在 `/mnt/user-data/workspace/<报告名>/` 保存原始数据、标准化事件、汇总结果与必要图形；按 `cecemate-format` 的网页规范直接生成 `/mnt/user-data/outputs/<报告名>.html`，并运行其 HTML 校验脚本。用户未指定时，报告名使用 `早期科技项目融资周报_YYYY年第WW周`。

## 工作流

1. 确认报告周期、区域、产业及是否纳入种子轮；没有歧义时直接采用默认值。
2. 阅读 `references/mcp-playbook.md`，用 PEVC 检索周期内融资事件，逐页原样保存至工作目录的 `raw/`，并按实时工具契约翻页至空列表。
3. 按 `references/data-contract.md` 做核心字段体检、标准化、复合去重、轮次与金额校验，再一次性计算全部汇总指标。
4. 从事件中选出 5–10 个重点项目。仅对这些项目调用 enterprise 与 person 做企业信息、图谱、股权和历史融资补充；详细顺序见 MCP playbook。
5. 阅读 `references/report-spec.md`，根据同一份汇总结果与已核验事实组织报告。事实、观察、待核事项分开写。
6. 读取 `/mnt/skills/public/cecemate-format/SKILL.md` 及其 `references/web-spec.md`，基于同一份已核验的汇总结果直接生成完整 HTML，写入 `/mnt/user-data/outputs/<报告名>.html`。按网页规范放置页头和页脚 Logo、`main` 末尾的免责声明；运行 `python /mnt/skills/public/cecemate-format/scripts/check_web_required.py /mnt/user-data/outputs/<报告名>.html`，未通过则修正后重检。HTML 不调用 `render.py`。
7. 按 `references/quality-checklist.md` 自检，通过后才交付文件路径、关键数字与数据缺口说明。

## 失败与降级

- 融资事件主检索失败：中止交付并说明失败服务、周期和已尝试的查询条件；不得以其他来源替代。
- 融资事件分页中途失败：默认中止交付，不把已取得页面当作完整周期数据；只有用户明确接受不完整报告时，才交付“截至第 N 页”的结果，并在标题、数据说明和交付消息中标明不完整。
- 企业详情、图谱或人物穿透失败：保留已取得的融资事实，将该项目标为“待核”或“仅融资信息”，并改选次优项目补足深度分析。
- 实控人只能以企业图谱返回的主体标识为起点继续查询；不能通过同名人搜索、法定代表人或推测替代。
- 工具或字段与 playbook 不一致：以实时工具描述为准，记录数据限制，不臆造新参数。

## 参考资料

- 首次取数或字段异常时阅读 `references/mcp-playbook.md`。
- 清洗、去重、金额或分类时阅读 `references/data-contract.md`。
- 编写正文与 HTML 信息架构时阅读 `references/report-spec.md`。
- 交付前阅读 `references/quality-checklist.md`。
