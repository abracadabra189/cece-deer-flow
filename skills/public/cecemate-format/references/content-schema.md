# CeCeMate content.json

所有 HTML / DOCX / PDF 渲染器只接受这一份结构化输入。不要让模型直接写
整页 HTML 或 DOCX；渲染器负责固定 Logo、免责声明、版心和样式。

## 顶层结构

```json
{
  "schema": "cecemate-content/v1",
  "meta": {
    "numbering": "chapter",
    "title": "行业洞察人工智能企业风险研究报告",
    "subtitle": "2026 年第三季度",
    "report_id": "CEM-2026-Q3-001",
    "period": "2026-10-20 至 2026-11-12",
    "scope": "企业风险数据",
    "author": "CeCeMate 自动生成",
    "date": "2026-11-18",
    "version": "v1.0",
    "header_title": "可选：页眉短标题，缺省用 title 截断 40 字"
  },
  "blocks": []
}
```

`meta.title` 和 `meta.date` 必填。`numbering` 取 `chapter`（默认）、`article`
或 `none`；`article` 用于合同类“第一条”编号。

`meta.chapter_page_break` 默认 `true`：DOCX 每个一级标题前分页；设为 `false`
可连续排版。

目录是**可选**的：内容里给 `toc` 才生成。没有 `toc` 时，DOCX 模板里的目录页
会被整页删除，不会留下空白页。

输出文件名为 `<title>.<ext>`；标题里的 Windows 非法字符会被替换为 `-`，没有
标题时回退为 `文档`。

## blocks

### heading

```json
{ "type": "heading", "level": 1, "text": "整体表现" }
```

`level` 只能是 1 / 2 / 3。DOCX 由渲染器根据 `meta.numbering` 自动生成编号，
输入里不要手写“一、”“1.1”；Web 按 `text` 原样输出（如需编号请直接写进 text）。

摘要、目录、附录、结论等不应参与章节编号的标题，加 `"numbered": false`：

```json
{ "type": "heading", "level": 1, "text": "摘要", "numbered": false }
```

### paragraph

```json
{ "type": "paragraph", "text": "正文第一段。\n\n正文第二段。" }
```

空行分段。只支持 `**加粗**` 这一种行内语法；不要塞 HTML 或 Markdown 表格。

### list

```json
{ "type": "list", "ordered": true, "items": ["第一项", "第二项"] }
```

### table

```json
{
  "type": "table",
  "caption": "表 1　经济核心指标情况",
  "source": "数据来源：行业洞察中台，统计截至 2026-11-12",
  "columns": [
    { "label": "指标", "align": "left", "width_cm": 5.18 },
    { "label": "本期", "align": "right", "width_cm": 4.0 }
  ],
  "rows": [["融资额（万元）", "18,426.6"]]
}
```

- `caption`、`source`、`columns`、`rows` 均必填；
- `columns[].align` 取 `left` 或 `right`；
- DOCX 必须为每列提供 `width_cm`；Web 可省略并按列均分；总和会自动缩放到 17.18cm；
- 每行长度必须等于 `columns` 长度。

### figure

```json
{
  "type": "figure",
  "src": "figures/chart-01.svg",
  "caption": "图 1　2026 年第三季度成交额趋势",
  "source": "数据来源：行业洞察中台",
  "width_cm": 17.18
}
```

- `src` 相对 `content.json` 所在目录；
- 只接受 SVG / PNG / JPG / WEBP；
- `caption`、`source` 必填；
- SVG 会被 HTML 内联、PDF 直接渲染、DOCX 用 PyMuPDF 以 300dpi 栅格化；
- SVG 不得包含 `<script>`、`foreignObject`、事件属性或外部引用。

### toc

```json
{ "type": "toc", "title": "目录" }
```

根据所有 `numbered` 标题生成目录。DOCX 使用静态条目 + `PAGEREF` 页码域，
content 里的 `toc` 只作为开关；Web 生成锚点链接，PDF 生成静态页码。
建议把 `toc` 放在 Web/PDF 正文最前面；如前面还有摘要，摘要页也会计入页码。

### page_break

```json
{ "type": "page_break" }
```

用于封面之后、摘要之后、目录之后三处允许的强制分页。

### callout

```json
{ "type": "callout", "tone": "warning", "text": "口径说明：..." }
```

`tone` 取 `info` / `success` / `warning` / `danger` / `neutral`，只影响描边和图标色。
DOCX 中按普通正文段落输出。

### Web 组件 blocks

以下 block 用于 HTML 网页；PDF/DOCX 会尽量按普通内容输出。

```json
{ "type": "hero", "title": "产业风险简报", "lead": "一句话导语。",
  "chips": ["报告编号：A-1", "更新时间：2026-11-24"],
  "tags": [{ "text": "信息", "tone": "info" }] }
```

```json
{ "type": "metrics", "items": [
  { "label": "成交额", "value": "18,426", "unit": "万元",
    "change": "↑ 23.8% 同比", "tone": "success" }
] }
```

```json
{ "type": "chart_row",
  "primary": { "src": "figures/a.svg", "caption": "图 1　趋势", "source": "来源：..." },
  "secondary": { "src": "figures/b.svg", "caption": "图 2　结构", "source": "来源：..." } }
```

```json
{ "type": "conclusion", "title": "综合研判",
  "paragraphs": ["判断正文。"],
  "findings_title": "关键发现",
  "findings": ["发现一", "发现二", "发现三"] }
```

```json
{ "type": "matrix", "items": [
  { "title": "主体 A", "status": "风险", "tone": "danger", "text": "说明。" }
] }
```

```json
{ "type": "timeline", "items": [
  { "date": "2026-11-24", "title": "事件", "text": "说明。" }
] }
```

```json
{ "type": "data_note", "source": "测试数据", "scope": "全量",
  "period": "2026 年", "limitations": ["样本有限"] }
```

```json
{ "type": "actions", "items": [
  { "label": "下载", "href": "#", "variant": "primary" }
] }
```

## 固定项

- Logo：由模板固定在页头/页脚（Web）或封面/页眉（DOCX），输入不得覆盖；
- 免责声明：由模板固定在篇尾，输入不得重复；
- 表格、图、章节编号：由渲染器落版，输入只提供内容。

## 输出约定

```
outputs/<title>/
├── <title>.html
├── <title>.docx
├── <title>.pdf
├── <title>.print.html   # PDF 的中间打印版
├── assets/logo.png
└── figures/
```

`meta.title` 决定文件名；标题里的非法字符会被替换为 `-`，没有标题时回退为 `文档`。

PDF 使用 WeasyPrint 从同一份 JSON 生成独立打印版；不要把 DOCX 转成 PDF。