# 展示点 → 图表映射（render_charts.py 内置 SVG 渲染器）

主引擎为内置纯 Python SVG 渲染器（离线、打印稳定、无 JS 依赖）；`chart-visualization`(AntV) 仅在交互版 HTML 需要 network/sankey 时补充使用，PDF 链路不依赖。

| 展示点 | type | 渲染函数 | 优化规则 |
| --- | --- | --- | --- |
| 综合评分+等级 | score_bar | render_score_bar | 五段等级条（较差/较低/一般/良好/优秀），指针标注等级字母；下方排名卡（全国 x/N、区域 y/M） |
| 六维评分 | radar | render_radar | 轴标签"维度\n等级|分值"；填充 20% 透明 |
| 产业链 | tree | render_tree | 上/中/下游三块横向树；节点超长 18 字省略+title 全量；环节企业数入块标题 |
| 企业趋势 | bar_grouped | render_bar_grouped | 存量/新注册双系列；异量级>10× 时自动改双轴 |
| 企业结构 | pyramid | render_pyramid | 层标签=名称+家数+占比；自顶向下上市→专精特新→高新→全部在营 |
| 注册资本/年限/轮次/融资类型 | donut | render_donut | >8 类合并"其他"；中心标注总量；标签=类名+家数,占比 |
| 区域分布 | map / hbar 降级 | render_hbar | 缺 `assets/geo/<adcode>.json` 时降级横向条形并注明 |
| 专利趋势 | bar_stacked | render_bar_stacked | 四类型堆叠（发明申请/实用新型/外观设计/发明授权）；图例置底 |
| 专利价值分项 | bubble_grid | render_bubble_grid | 行=三维、列=10..1 分；气泡面积∝件数 |
| 融资趋势/创投趋势 | dual_bar_line | render_dual_bar_line | 左轴金额(亿元)柱、右轴件数线；轴单位标注 |
| 财务指数 | line_index | render_line_index | 基线 100 参考线；总/平均双线 |
| 融资区域/关键技术等 Top10 | hbar / table | render_hbar | 降序、值标签外置；文本长表优先 table |
| 龙头/申请人/园区/事件 | table | build_html 表格 | 跨页重复表头；长文本截断+附录 |

通用规则：色板取 `assets/theme.json`；标签防重叠（自动旋转/抽稀）；数值轴自动 ticks；所有图带图题+数据范围块；图高默认 90mm（tree 120mm、score_bar 60mm）。
