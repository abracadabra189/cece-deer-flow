# cecemate-format 示例

在当前技能目录下运行：

按需选择格式，不要默认三件套：

```bash
# 只要 DOCX
python scripts/render.py examples/sample-content.json --out /tmp/cecemate-sample --formats docx

# DOCX + HTML
python scripts/render.py examples/sample-content.json --out /tmp/cecemate-sample --formats docx,html

# 三件套
python scripts/render.py examples/sample-content.json --out /tmp/cecemate-sample --formats html,docx,pdf
```

也可以继续单独调用 `render_web.py` / `render_docx.py` / `render_pdf.py`；
`render.py` 已经自动运行所选格式的 checker，不需要再单独 review。

输出：

```text
/tmp/cecemate-sample/
├── 行业洞察人工智能企业风险研究报告.html
├── 行业洞察人工智能企业风险研究报告.docx
├── 行业洞察人工智能企业风险研究报告.pdf
├── 行业洞察人工智能企业风险研究报告.print.html
├── assets/logo.png
└── figures/
```

注意：

- `figures/chart.svg` 是示例图，实际使用时替换为你的 SVG/PNG；
- DOCX 目录是 Word TOC 域，打开后如未自动更新，右键目录选择“更新域”；
- 代码 checker 只校验 Logo、免责声明、占位符、外部资源和输出可解析；
- 表格 `width_cm` 在 DOCX 中必填，Web 可省略。