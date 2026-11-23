---
name: cecemate-web-spec
display_name: CeCeMate 网页规范
description: 当用户要求交付 HTML 网页、静态数据报告、产业可视化页面或网页制品时，按 CeCeMate 设计令牌、品牌、响应式和验收标准生成并校验。仅适用于网页交付，不处理 DOCX/PDF 排版。
---

# CeCeMate 网页产出规范

用于生成单文件 HTML 或静态网页交付物。内容事实、数据口径和分析结论仍以用户需求与已核验资料为准；本技能只约束页面结构、视觉令牌、可访问性和交付质量。

## 何时使用

- 用户要求 HTML 网页、产业可视化页面、可交互数据报告、专题页或静态网页制品。
- 用户要求将已有分析制作成可浏览、可打印的 CeCeMate 页面。

Word、DOCX、PDF 或打印版文档请改用 `cecemate-doc-spec`。

## 工作流程

1. 先读取 [完整网页规范](references/web-spec.md)，按页面场景选择模块和图表形式。
2. 使用 [行业洞察 Logo](assets/logo.png)，生成页面中的图片路径统一写为 `assets/logo.png`；页头和页脚各出现一次，不得拉伸、滤镜化或隐藏。
3. 按规范生成 HTML，使用 CSS 设计令牌，提供语义结构、响应式布局和图表替代说明。
4. 对生成页面执行：

   ```bash
   python /mnt/skills/public/cecemate-web-spec/check/check_web.py <页面.html>
   ```

5. 如检查失败，依据规则编号修正并重跑；通过后在桌面与窄屏宽度下复核版式、图表尺寸、数据可读性和打印表现。

## 必须保留的交付要素

- `assets/logo.png` 对应的行业洞察 Logo，页头、页脚各一处；
- `<header>`、`<main>`、`<footer>` 语义结构；
- `main` 的最后一个区块为免责声明，包含“内容由 AI 生成，请核实重要信息”；
- 合规 viewport、页面标题、内联 favicon，以及规范中的核心 CSS 设计令牌。

## 校验边界

`check_web.py` 只检查 HTML 的确定性结构与禁用项，包括 CeCeMate 标识、内联 favicon、核心 `:root` 令牌和外部脚本白名单；它不验证页面的审美、图表数据正确性、浏览器截图效果或所有 CSS 视觉细节。本地在技能根目录测试时可用 `python check/check_web.py <页面.html>`。
