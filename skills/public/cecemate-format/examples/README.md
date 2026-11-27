# cecemate-format 示例

在当前技能目录下运行：

按需选择格式，不要默认三件套：

```bash
# 默认只出 DOCX（不传 --formats 也可以）
python scripts/render.py examples/sample-content.json --out /tmp/cecemate-sample

# 明确要 DOCX + PDF
python scripts/render.py examples/sample-content.json --out /tmp/cecemate-sample --formats docx,pdf
```

HTML 按网页规范直接生成，并单独运行 `check_web_required.py`；不通过 `render.py`。
`render.py` 已经自动运行所选 DOCX/PDF 的 checker，不需要再单独 review。

三件套输出示例：

```text
/tmp/cecemate-sample/
├── 行业洞察人工智能企业风险研究报告.docx
├── 行业洞察人工智能企业风险研究报告.pdf
├── 行业洞察人工智能企业风险研究报告.print.html
├── assets/logo.png
└── figures/
```

注意：

- `figures/chart.svg` 是示例图，实际使用时替换为你的 SVG/PNG；
- DOCX 目录是 Word TOC 域，打开后如未自动更新，右键目录选择“更新域”；
- HTML checker 只校验 Logo 与免责声明；DOCX/PDF checker 保持各自的交付完整性校验；
- 表格 `width_cm` 在 DOCX 中必填。
