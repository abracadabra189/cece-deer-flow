---
name: cecemate-doc-spec
display_name: CeCeMate 文档规范
description: 当用户要求交付 Word、DOCX、PDF、研究报告、分析简报、方案、提案、会议纪要或打印稿时，按 CeCeMate 文档版式、品牌和验收标准生成并校验。仅适用于文档交付，不处理纯 HTML 网页。
---

# CeCeMate 文档产出规范

用于生成可编辑、可打印的 CeCeMate 文档交付物。内容事实、数据口径和分析结论仍以用户需求与已核验资料为准；本技能只约束文档结构、版式和交付质量。

## 何时使用

- 用户明确需要 `.docx`、PDF、打印稿或以文档形式交付的报告、方案、简报、纪要、手册、合同和附表。
- 用户要求将已有内容整理为正式 CeCeMate 文档。

纯 HTML 网页、交互式报告或网页制品请改用 `cecemate-web-spec`。

## 工作流程

1. 先读取 [完整文档规范](references/document-spec.md)，按交付类型选择适用模板。
2. 使用 [行业洞察 Logo](assets/logo.png)，不得重绘、拉伸或替换为文字；生成 DOCX 时将其嵌入页眉，文档内部会自行打包图片，不能改为外部相对路径引用。
3. 生成可编辑的 DOCX；需要 PDF 时，在 DOCX 校验通过后再导出 PDF。不要把整页内容渲染成图片。
4. 对生成的 DOCX 执行：

   ```bash
   python /mnt/skills/public/cecemate-doc-spec/check/check_doc.py <文档.docx>
   ```

5. 如检查失败，依据规则编号修正并重跑；通过后再进行人工/模型复核：内容层级、表格可读性、分页、Logo 清晰度、PDF 渲染效果和事实口径。

## 必须保留的交付要素

- `assets/logo.png` 对应的行业洞察 Logo；
- 文末免责声明“内容由 AI 生成，请核实重要信息”；
- 可更新或可识别的页码字段；
- 表格使用固定布局和明确列宽，避免表头与数据错列。

## 校验边界

`check_doc.py` 检查 DOCX 内部结构，例如页眉中嵌入的指定 Logo、唯一且位于文末的免责声明、页码字段、A4 页面节信息和表格网格；它不替代打开文档后的视觉检查，也不验证数据事实、断页美观或 PDF 渲染。本地在技能根目录测试时可用 `python check/check_doc.py <文档.docx>`。
