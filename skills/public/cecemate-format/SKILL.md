---
name: cecemate-format
display_name: CeCeMate 格式交付
description: 当用户需要交付 CeCeMate 风格的 HTML、DOCX 或 PDF 报告、简报、方案、会议纪要、产品手册或财务附表时使用；适用于需要统一品牌格式与交付校验的正式制品。
---

# CeCeMate 格式交付

本技能把正式文档内容与版式分开：DOCX/PDF 使用 `content.json` 和渲染器；HTML
则由模型直接生成单文件网页，并按网页规范完成有信息层级的视觉编排。不要手写 DOCX。

## 工作流程

1. 交付 DOCX/PDF 时，先读 [content.json 结构](references/content-schema.md)。
2. 交付 HTML 时，先读 [网页规范](references/web-spec.md)。根据内容选择版式重点，
   直接写出完整 HTML；不要为了套模板而虚构指标卡、图表或时间线。
   - 用页头 Logo、主体内容、篇尾免责声明、页脚 Logo 构成稳定骨架；
   - 视觉以信息层级为先：数据页可突出表格与静态 SVG，洞察页可突出结论与关键发现；
     同一页面不要堆叠所有模块；
   - HTML 可使用内联 CSS/JS 和静态 SVG，不强制使用 ECharts 或任何图表库；
   - 生成后必须运行 `check_web_required.py`。该脚本只硬校验 Logo 和免责声明，
     不把视觉规则变成机械失败条件。
3. HTML 输出到 `/mnt/user-data/outputs/<名称>.html`。使用内联 base64 Logo 时，先在
   沙箱读取 `assets/logo.png` 生成 data URI；也可在输出目录复制
   `assets/logo.png` 并以相对路径引用。Logo 不得由文字或自绘图形替代。
4. 只有交付 DOCX/PDF 时，才在 `/mnt/user-data/workspace/` 下创建：

   ```text
   <名称>/
   ├── content.json
   └── figures/
       ├── chart-01.svg
       └── chart-02.svg
   ```

5. 图形只提供 SVG / PNG 文件，不要使用 Mermaid 或外部图表库。
6. **默认只生成 DOCX，绝不默认三件套。** 用户明确要 HTML/PDF 才加格式；
   不要同时调用三个 renderer。

   ```bash
   # 默认只出 DOCX
   python /mnt/skills/public/cecemate-format/scripts/render.py \
     /mnt/user-data/workspace/<名称>/content.json \
     --out /mnt/user-data/outputs/<名称>

   # 明确要 DOCX + PDF
   python /mnt/skills/public/cecemate-format/scripts/render.py \
     /mnt/user-data/workspace/<名称>/content.json \
     --out /mnt/user-data/outputs/<名称> \
     --formats docx,pdf
   ```

   HTML 不经过 `render.py`，按本技能的网页规范直接交付。

7. `render.py` 已自动运行 DOCX/PDF 的 checker，**不需要再单独 review**。HTML
   生成后单独调用 `check_web_required.py`；只有调试单个文档格式时，才单独调用
   `check_doc_required.py` / `check_pdf_required.py`。

8. PDF 使用 WeasyPrint 从同一份 `content.json` 生成独立打印版，不要求
   DOCX→PDF 同源。PDF 与 DOCX 各自按文档规范落版；checker 只查品牌与交付完整性。

## 代码校验（品牌与交付完整性）

- 行业洞察 Logo：Web 页头/页脚各一次，支持内联 base64（单文件交付例外），
  alt 非空、hash 一致、未隐藏/拉伸；DOCX 封面 1.10cm、页眉 0.55cm，字节与
  `assets/logo.png` 一致、比例 5.27:1；
  PDF 封面/页眉同理；
- 免责声明：Web 在 `<main>` 最后一节；DOCX 在正文最后一个非空段落；PDF 在
  最后一页；全文仅一次，页脚不得重复，不得隐藏；
- DOCX 不得外链图片/对象；HTML 的视觉与工程约束见网页规范，人工复核；
- DOCX 是有效 zip，PDF 非空且可打开；
- DOCX 连续分页符之间没有内容（空白页的常见来源）。

`check_*_required.py` **不检查** A4、页边距、字体、字号、页码域、表格网格、
分页、留白、颜色、无障碍等。这些由模板、渲染器和下面的文本要求负责。

## 文本要求（模型遵守，不由脚本强制）

- HTML 为单文件预览/下载，优先内联品牌 Logo；也可随 HTML 交付同级
  `assets/logo.png`，但不得使用远程 Logo；
- 封面按团队要求不绘制 0.5pt 分隔线，只保留大 Logo；正文页眉文档名右侧；
- DOCX 封面独立成节，A4，上下 2.40cm、左右 1.91cm，页脚只有 PAGE 域；
- 正文 10.5pt / 17.3pt 固定行距 / 首行缩进 2 字符；
- 表格 `tblLayout=fixed`、`tblGrid` 列宽、表头跨页重复、行不跨页，数值右对齐；
- 所有图形宽度不超过 17.18cm、等比缩放；SVG 不含脚本、foreignObject、外链；
- 目录页、分页、空白页、孤行、图表跨页、HTML 视觉层级与响应式等，按
  `references/doc-spec.md` 和 `references/web-spec.md` 人工复核。

## 边界

- `templates/doc.docx` 是骨架（封面 + 可选目录 + 正文占位），不是固定页数交付物；
  Word 会按内容自动续页。摘要用 `heading` + `paragraph` 表达。
- 目录是可选的：内容里给 `toc` 才生成；没有 `toc` 时，DOCX 模板的目录页
  会整页删除。
- PDF 打印版可使用标题区、指标卡、静态 SVG、结论、矩阵、时间线、数据说明、
  标签、提示块与动作按钮等结构化内容块；HTML 不受这些块约束。
- `meta.chapter_page_break` 默认 `true`，DOCX 每个一级标题前分页；设为 `false`
  可连续排版。
- `check_web_required.py` 只检查 Logo 与免责声明；`check_doc_required.py`、
  `check_pdf_required.py` 保持各自现有的品牌与交付完整性检查。HTML 的版式、字体、
  表格、颜色、图表数据正确性和实际预览仍需人工复核。
- DOCX 模板在 `templates/doc.docx`，由 `scripts/build_doc_template.py` 生成；
  不要直接手改模板。
- 模板与 `assets/logo.png` 在技能目录中是只读的；渲染输出必须写到
  `/mnt/user-data/outputs/`。

## 输出命名

文件名为 `<meta.title>.<ext>`；标题里的 Windows 非法字符会替换为 `-`，
没有标题时回退为 `文档.<ext>`。例如：

```text
行业洞察人工智能企业风险研究报告.html
行业洞察人工智能企业风险研究报告.docx
行业洞察人工智能企业风险研究报告.pdf
行业洞察人工智能企业风险研究报告.print.html
```

## 示例与评测

- `examples/sample-content.json`：最小可跑输入；
- `evals/evals.json`：4 条评测提示词。

## 校验命令

```bash
python scripts/build_doc_template.py
python scripts/check_doc_required.py templates/doc.docx --allow-placeholders
python scripts/check_web_required.py /path/to/<title>.html
```
