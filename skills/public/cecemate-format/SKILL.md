---
name: cecemate-format
display_name: CeCeMate 格式交付
description: 当用户需要交付 CeCeMate 风格的 HTML、DOCX 或 PDF 报告、简报、方案、会议纪要、产品手册、财务附表时，用结构化 content.json 经固定模板渲染，强制保留行业洞察 Logo、篇尾免责声明、CeCeMate 版式和表格列宽。适用于需要可校验、统一品牌格式的正式交付物。
---

# CeCeMate 格式交付

本技能把内容与版式分开：模型只写 `content.json`，渲染器负责 Logo、免责声明、
版心、字体、表格网格和输出格式。不要直接手写整页 HTML 或 DOCX。

## 工作流程

1. 先读 [content.json 结构](references/content-schema.md)。
2. 在 `/mnt/user-data/workspace/` 下创建：

   ```text
   <名称>/
   ├── content.json
   └── figures/
       ├── chart-01.svg
       └── chart-02.svg
   ```

3. 图形只提供 SVG / PNG 文件，不要使用 ECharts、Mermaid 或外部图表库。
4. **默认只生成 DOCX，绝不默认三件套。** 用户明确要 HTML/PDF 才加格式；
   不要同时调用三个 renderer。

   ```bash
   # 默认只出 DOCX
   python /mnt/skills/public/cecemate-format/scripts/render.py \
     /mnt/user-data/workspace/<名称>/content.json \
     --out /mnt/user-data/outputs/<名称>

   # 明确要 DOCX + HTML
   python /mnt/skills/public/cecemate-format/scripts/render.py \
     /mnt/user-data/workspace/<名称>/content.json \
     --out /mnt/user-data/outputs/<名称> \
     --formats docx,html
   ```

   只有用户明确要求“三件套”时，才使用 `--formats html,docx,pdf`。

5. `render.py` 已自动运行所选格式的 checker，**不需要再单独 review**，
   也不要分别调用三个 checker。只有调试单个格式时，才单独调用
   `check_web_required.py` / `check_doc_required.py` / `check_pdf_required.py`。

6. PDF 使用 WeasyPrint 从同一份 `content.json` 生成独立打印版，不要求
   DOCX→PDF 同源。PDF 与 DOCX 各自按文档规范落版；checker 只查品牌与交付完整性。

## 代码校验（品牌与交付完整性）

- 行业洞察 Logo：Web 页头/页脚各一次，支持内联 base64（单文件交付例外），
  alt 非空、hash 一致、未隐藏/拉伸；DOCX 封面 1.10cm、页眉 0.55cm，字节与
  `assets/logo.png` 一致、比例 5.27:1；
  PDF 封面/页眉同理；
- 免责声明：Web 在 `<main>` 最后一节；DOCX 在正文最后一个非空段落；PDF 在
  最后一页；全文仅一次，页脚不得重复，不得隐藏；
- 模板占位符：不得残留 `{{TITLE}}`、`{{CONTENT_PLACEHOLDER}}` 等；
- 外部资源：不得引用远程脚本、样式、图片、iframe，DOCX 不得外链图片/对象；
- 输出可解析：HTML 可解析、DOCX 是有效 zip、PDF 非空且可打开；
- DOCX 连续分页符之间没有内容（空白页的常见来源）。

`check_*_required.py` **不检查** A4、页边距、字体、字号、页码域、表格网格、
分页、留白、颜色、无障碍等。这些由模板、渲染器和下面的文本要求负责。

## 文本要求（模型遵守，不由脚本强制）

- Web 为单文件预览/下载，行业洞察 Logo 内联 base64；这是对 web-spec §14
  相对路径要求的团队例外；
- 封面按团队要求不绘制 0.5pt 分隔线，只保留大 Logo；正文页眉文档名右侧；
- DOCX 封面独立成节，A4，上下 2.40cm、左右 1.91cm，页脚只有 PAGE 域；
- 正文 10.5pt / 17.3pt 固定行距 / 首行缩进 2 字符；
- 表格 `tblLayout=fixed`、`tblGrid` 列宽、表头跨页重复、行不跨页，数值右对齐；
- 所有图形宽度不超过 17.18cm、等比缩放；SVG 不含脚本、foreignObject、外链；
- 目录页、分页、空白页、孤行、图表跨页、Web 模块与响应式等，按
  `references/doc-spec.md` 和 `references/web-spec.md` 人工复核。

## 边界

- `templates/doc.docx` 是骨架（封面 + 可选目录 + 正文占位），不是固定页数交付物；
  Word 会按内容自动续页。摘要用 `heading` + `paragraph` 表达。
- 目录是可选的：内容里给 `toc` 才生成；没有 `toc` 时，DOCX 模板的目录页
  会整页删除。
- Web 已支持 M1 标题区、M2 指标卡、M3 主辅图表、M5 结论/关键发现、M6
  矩阵卡、M7 时间线、M8 数据说明、标签、提示块、动作按钮。
- Web 模块走渲染前预检：M2 必须 2–4 张卡、M5 findings 3–5 条、M6 4/6 张卡、
  M7 4–7 个节点、M8 必须存在且 source/scope/period 非空；不通过直接失败。
  不增加 checker 步骤。
- `meta.chapter_page_break` 默认 `true`，DOCX 每个一级标题前分页；设为 `false`
  可连续排版。
- `check_web_required.py`、`check_doc_required.py`、`check_pdf_required.py`
  只检查 Logo、免责、占位符、外部资源、空白页和输出可解析；版式、字体、
  表格、颜色、图表数据正确性和 Word/WPS 实际渲染仍需人工复核。这样避免把
  非致命版式问题变成额外重试步骤。
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