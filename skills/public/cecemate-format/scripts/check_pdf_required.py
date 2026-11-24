#!/usr/bin/env python3
"""CeCeMate PDF 代码校验。

校验品牌与交付完整性：
- 封面 1.10cm Logo、每页 0.55cm 页眉 Logo，比例 5.27:1；
- 免责短句只在最后一页出现一次；
- 模板占位符未残留；
- PDF 非空且可打开。

A4、页边距、页码、分页、表格跨页、字体嵌入等要求写在 SKILL.md 中，由渲染器
和人工复核负责，脚本不拦截。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz

DISCLAIMER = "内容由 AI 生成，请核实重要信息"
PLACEHOLDERS = {
    "{{TITLE}}",
    "{{SUBTITLE}}",
    "{{META}}",
    "{{DATE}}",
    "{{VERSION}}",
    "{{PRINT_VARS}}",
    "{{DOC_NAME}}",
    "{{CONTENT}}",
    "{{DISCLAIMER}}",
    "{{LOGO_SRC}}",
}
COVER_LOGO_HEIGHT = 31.18
HEADER_LOGO_HEIGHT = 15.59
TOLERANCE = 2.0
EXPECTED_RATIO = 2529 / 480
RATIO_TOLERANCE = 0.02


def _image_sizes(page: fitz.Page) -> list[tuple[float, float]]:
    sizes: list[tuple[float, float]] = []
    for image in page.get_images(full=True):
        for rect in page.get_image_rects(image[0]):
            sizes.append((float(rect.height), float(rect.width)))
    return sizes


def validate(pdf: Path, config_path: Path) -> list[str]:
    if pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        return ["P-PACKAGE：请提供存在的 PDF 文件。"]
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        disclaimer = config["doc"]["disclaimer"]["text"]
    except (OSError, KeyError, ValueError) as exc:
        return [f"P-CONFIG：无法读取 brand-config.json 的免责声明：{exc}"]

    try:
        document = fitz.open(str(pdf))
    except Exception as exc:
        return [f"P-PACKAGE：无法读取 PDF：{exc}"]
    if document.page_count < 1:
        return ["P-PACKAGE：PDF 为空。"]

    issues: list[str] = []
    all_text = "".join(page.get_text("text") for page in document)
    remaining = sorted(marker for marker in PLACEHOLDERS if marker in all_text)
    if remaining:
        issues.append(f"P-PLACEHOLDER：模板占位符未替换：{', '.join(remaining)}")

    cover_sizes = _image_sizes(document[0])
    cover_ok = False
    for height, width in cover_sizes:
        if abs(height - COVER_LOGO_HEIGHT) <= TOLERANCE:
            cover_ok = True
            if abs(width / height - EXPECTED_RATIO) / EXPECTED_RATIO > RATIO_TOLERANCE:
                issues.append("P-LOGO-ASPECT：封面 Logo 不得拉伸，必须保持 5.27:1。")
    if not cover_ok:
        issues.append("P-LOGO-COVER：封面必须包含约 1.10cm 的 Logo。")

    for index in range(1, document.page_count):
        sizes = _image_sizes(document[index])
        header_ok = False
        for height, width in sizes:
            if abs(height - HEADER_LOGO_HEIGHT) <= TOLERANCE:
                header_ok = True
                if abs(width / height - EXPECTED_RATIO) / EXPECTED_RATIO > RATIO_TOLERANCE:
                    issues.append(f"P-LOGO-ASPECT：第 {index + 1} 页页眉 Logo 不得拉伸。")
        if not header_ok:
            issues.append(f"P-LOGO-HEADER：第 {index + 1} 页缺少约 0.55cm 的页眉 Logo。")

    last_text = document[-1].get_text("text")
    if disclaimer not in last_text:
        issues.append("P-DISCLAIMER：免责短句必须出现在最后一页。")
    for index in range(0, document.page_count - 1):
        if disclaimer in document[index].get_text("text"):
            issues.append(f"P-DISCLAIMER：免责短句不得出现在第 {index + 1} 页（只允许篇尾一次）。")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 CeCeMate PDF 的 Logo 与免责声明。")
    parser.add_argument("pdf", type=Path, help="待检查的 PDF 文件")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "brand-config.json",
        help="brand-config.json 路径（默认使用技能根目录）",
    )
    args = parser.parse_args()

    issues = validate(args.pdf, args.config)
    if issues:
        print("PDF 检查未通过：", file=sys.stderr)
        print("\n".join(f"- {issue}" for issue in issues), file=sys.stderr)
        return 1
    print("PDF Logo 与免责声明检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
