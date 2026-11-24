#!/usr/bin/env python3
"""CeCeMate HTML 代码校验。

校验品牌与交付完整性：
- 页头、页脚各一张 Logo（相对路径或允许的 base64），alt 非空、hash 一致、未隐藏/拉伸；
- main 的最后一个 section 是 .disclaimer，包含逐字免责短句，页脚不重复；
- 模板占位符未残留；
- 无远程脚本/样式/图片/iframe；
- 文件非空且可解析。

字体、版心、表格、图表、响应式等要求写在 SKILL.md 中，由模型和人工复核，
脚本不执行、不拦截。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

DISCLAIMER = "内容由 AI 生成，请核实重要信息"
PLACEHOLDERS = {
    "{{TITLE}}",
    "{{SUBTITLE}}",
    "{{META}}",
    "{{DATE}}",
    "{{VERSION}}",
    "{{CSS_VARS}}",
    "{{PRINT_VARS}}",
    "{{HEADER_META}}",
    "{{CONTENT}}",
    "{{CONTENT_PLACEHOLDER}}",
    "{{DISCLAIMER}}",
    "{{DISCLAIMER_SHORT}}",
    "{{DISCLAIMER_LONG}}",
    "{{FOOTER_SOURCE}}",
    "{{FOOTER_RIGHT}}",
    "{{LOGO_SRC}}",
}
VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


class PageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.header_logo = False
        self.footer_logo = False
        self.logo_sources: list[str] = []
        self.logo_tags: list[dict[str, str]] = []
        self.external_resources: list[str] = []
        self.footer_text: list[str] = []
        self.main_sections: list[tuple[dict[str, str], str]] = []
        self._section_stack: list[tuple[dict[str, str], list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): (value or "") for key, value in attrs}
        if tag == "img":
            src = attrs_dict.get("src", "").replace("\\", "/")
            if src.endswith("assets/logo.png") or src.startswith("data:image/png;base64,"):
                self.logo_sources.append(src)
                self.logo_tags.append(attrs_dict)
                if "header" in self.stack and attrs_dict.get("alt", "").strip():
                    self.header_logo = True
                if "footer" in self.stack and attrs_dict.get("alt", "").strip():
                    self.footer_logo = True
            if src.startswith(("http://", "https://", "//")):
                self.external_resources.append(f"img:{src}")
        if tag in {"script", "iframe", "object", "embed", "link", "source"}:
            resource = attrs_dict.get("src") or attrs_dict.get("href") or ""
            if tag in {"iframe", "object", "embed"} or resource.startswith(("http://", "https://", "//")):
                self.external_resources.append(f"{tag}:{resource or '<inline>'}")
        if "javascript:" in " ".join(attrs_dict.values()).lower():
            self.external_resources.append(f"{tag}:javascript")
        if tag == "section" and "main" in self.stack:
            self._section_stack.append((attrs_dict, []))
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._section_stack:
            self._section_stack[-1][1].append(data)
        if "footer" in self.stack:
            self.footer_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._section_stack:
            attrs, text = self._section_stack.pop()
            self.main_sections.append((attrs, "".join(text)))
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break


def _load_json(path: Path) -> dict:
    import json

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate(page: Path, config_path: Path) -> list[str]:
    if page.suffix.lower() not in {".html", ".htm"} or not page.is_file():
        return ["W-PACKAGE：请提供存在的 HTML 文件。"]
    try:
        source = page.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return ["W-PACKAGE：HTML 必须使用 UTF-8 编码。"]

    try:
        config = _load_json(config_path)
        expected_hash = config["assets"]["logo"]["sha256"]
        allow_base64 = bool(config.get("web", {}).get("engineering", {}).get("allow_logo_base64"))
    except (OSError, KeyError, ValueError) as exc:
        return [f"W-CONFIG：无法读取 brand-config.json 的 logo.sha256：{exc}"]

    parser = PageInspector()
    parser.feed(source)
    parser.close()

    issues: list[str] = []
    if not source.strip():
        issues.append("W-PACKAGE：HTML 为空。")
    remaining = sorted(marker for marker in PLACEHOLDERS if marker in source)
    if remaining:
        issues.append(f"W-PLACEHOLDER：模板占位符未替换：{', '.join(remaining)}")
    external = list(parser.external_resources)
    if re.search(r"url\(\s*['\"]?(?:https?:)?//", source, re.IGNORECASE):
        external.append("css:url(remote)")
    if external:
        issues.append(f"W-EXTERNAL：产出物不得引用远程脚本、样式、图片或 iframe：{', '.join(sorted(set(external)))}")

    if not parser.header_logo or not parser.footer_logo:
        issues.append("W-LOGO：页头和页脚必须使用带非空 alt 的 Logo。")
    if not parser.logo_sources:
        issues.append("W-LOGO：未找到 Logo。")
    for attrs in parser.logo_tags:
        style = attrs.get("style", "").lower().replace(" ", "")
        if any(token in style for token in ("display:none", "visibility:hidden", "opacity:0")):
            issues.append("W-LOGO-HIDDEN：Logo 不得隐藏。")
        if "width" in attrs or "height" in attrs or "width:" in style or "height:" in style:
            issues.append("W-LOGO-STRETCH：Logo 不得写死宽高，应由 height + width:auto 等比缩放。")

    relative_sources = [src for src in parser.logo_sources if src.endswith("assets/logo.png")]
    inline_sources = [src for src in parser.logo_sources if src.startswith("data:image/png;base64,")]
    if relative_sources:
        logo_path = page.parent / "assets" / "logo.png"
        if not logo_path.is_file():
            issues.append("W-LOGO-FILE：页面同级缺少 assets/logo.png。")
        else:
            actual_hash = hashlib.sha256(logo_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                issues.append("W-LOGO-HASH：assets/logo.png 与 brand-config.json 记录的 Logo 不一致。")
    for data_uri in inline_sources:
        if not allow_base64:
            issues.append("W-LOGO-BASE64：brand-config.json 未允许内联 base64 Logo。")
        try:
            payload = base64.b64decode(data_uri.split(",", 1)[1], validate=True)
        except (ValueError, IndexError):
            issues.append("W-LOGO-HASH：内联 Logo 不是有效的 base64 PNG。")
            continue
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            issues.append("W-LOGO-HASH：内联 Logo 与品牌资产不一致。")
    if any(src.startswith(("http://", "https://", "//")) for src in parser.logo_sources):
        issues.append("W-LOGO-REMOTE：Logo 不得引用远程地址。")

    if not parser.main_sections:
        issues.append("W-DISCLAIMER：main 中没有 section。")
    else:
        attrs, text = parser.main_sections[-1]
        classes = attrs.get("class", "").split()
        if "disclaimer" not in classes or DISCLAIMER not in text:
            issues.append("W-DISCLAIMER：main 的最后一个 section 必须是包含完整免责短句的 .disclaimer。")
        style = attrs.get("style", "").lower().replace(" ", "")
        if any(token in style for token in ("display:none", "visibility:hidden", "opacity:0")):
            issues.append("W-DISCLAIMER-HIDDEN：免责声明不得隐藏。")

    if DISCLAIMER in "".join(parser.footer_text):
        issues.append("W-DISCLAIMER-FOOTER：页脚不得重复免责声明。")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 CeCeMate HTML 的 Logo 与免责声明。")
    parser.add_argument("page", type=Path, help="待检查的 HTML 文件")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "brand-config.json",
        help="brand-config.json 路径（默认使用技能根目录）",
    )
    args = parser.parse_args()

    issues = validate(args.page, args.config)
    if issues:
        print("HTML 检查未通过：", file=sys.stderr)
        print("\n".join(f"- {issue}" for issue in issues), file=sys.stderr)
        return 1
    print("HTML Logo 与免责声明检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
