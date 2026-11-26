# 交付前自检清单

- [ ] `validation_report.json.passed == true`，L3 未匹配数字 = 0
- [ ] 每图每表带"截至/数据来源"块；方法论章列出全部 limitations
- [ ] 章节顺序 = 封面→摘要→五章→方法论→结论→附录→封底；附录 C 图表索引页码正确
- [ ] 封面版式/页眉/页脚符合 html-rules.md §1–§4（logo、导航条、免责句、页码起始 1）
- [ ] `check_html.json`：外链=0、溢出块=0、svg 数=charts.json 数、无 NaN/undefined 泄漏
- [ ] 表格跨页重复表头；数值右对齐千分位；单位入表头
- [ ] 事实强调蓝、风险红使用正确；分析段三段式且推断有标注
- [ ] PDF 页数 = HTML `.page` 数；第 2 页含页眉与页码（有 PDF 引擎时）
- [ ] 降级项（图表→表格、无 PDF 引擎等）已在交付说明与 summary 中声明
