#!/usr/bin/env python3
"""检查 CeCeMate HTML 交付物的核心结构约束。"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


DISCLAIMER = "内容由 AI 生成，请核实重要信息"
REQUIRED_TOKENS = {"--blue-600", "--gray-000", "--gray-400", "--gray-1200", "--fs-body"}
ALLOWED_EXTERNAL_SCRIPTS = {"https://fastly.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"}


class PageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.html_lang = ""
        self.title = ""
        self._in_title = False
        self._in_style = False
        self.styles: list[str] = []
        self._style_buffer: list[str] = []
        self.viewport = ""
        self.generator = ""
        self.favicon_href = ""
        self.script_sources: list[str] = []
        self.has_iframe = False
        self.has_form = False
        self.header_logo = False
        self.footer_logo = False
        self.main_sections: list[tuple[dict[str, str], str]] = []
        self._section_stack: list[tuple[dict[str, str], list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): (value or "") for key, value in attrs}
        if tag == "html":
            self.html_lang = attrs_dict.get("lang", "")
        elif tag == "meta":
            name = attrs_dict.get("name", "").lower()
            if name == "viewport":
                self.viewport = attrs_dict.get("content", "")
            elif name == "generator":
                self.generator = attrs_dict.get("content", "")
        elif tag == "link" and "icon" in attrs_dict.get("rel", "").lower():
            self.favicon_href = attrs_dict.get("href", "")
        elif tag == "script" and attrs_dict.get("src"):
            self.script_sources.append(attrs_dict["src"])
        elif tag == "title":
            self._in_title = True
        elif tag == "style":
            self._in_style = True
            self._style_buffer = []
        elif tag == "iframe":
            self.has_iframe = True
        elif tag == "form":
            self.has_form = True
        elif tag == "img" and attrs_dict.get("src", "").replace("\\", "/").endswith("assets/logo.png") and attrs_dict.get("alt", "").strip():
            if "header" in self.stack:
                self.header_logo = True
            if "footer" in self.stack:
                self.footer_logo = True

        if tag == "section" and self.stack and self.stack[-1] == "main":
            self._section_stack.append((attrs_dict, []))
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_style:
            self._style_buffer.append(data)
        if self._section_stack:
            self._section_stack[-1][1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "style":
            self._in_style = False
            self.styles.append("".join(self._style_buffer))
        if tag == "section" and self._section_stack:
            attrs, text = self._section_stack.pop()
            self.main_sections.append((attrs, "".join(text)))
        if self.stack:
            self.stack.pop()


def _root_tokens(styles: list[str]) -> set[str]:
    clean_css = re.sub(r"/\*.*?\*/", "", "\n".join(styles), flags=re.DOTALL)
    root_blocks = re.findall(r":root\s*\{([^{}]*)\}", clean_css, flags=re.IGNORECASE)
    return {token for token in REQUIRED_TOKENS if any(re.search(rf"{re.escape(token)}\s*:", block) for block in root_blocks)}


def validate(path: Path) -> list[str]:
    if path.suffix.lower() not in {".html", ".htm"} or not path.is_file():
        return ["W-PACKAGE：请提供存在的 HTML 文件。"]
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return ["W-PACKAGE：HTML 必须使用 UTF-8 编码。"]
    parser = PageInspector()
    parser.feed(source)
    parser.close()

    issues: list[str] = []
    if parser.html_lang.lower() != "zh-cn":
        issues.append('W-LANG：html 必须设置 lang="zh-CN"。')
    if not parser.title.strip():
        issues.append("W-TITLE：页面必须包含非空 title。")
    viewport = parser.viewport.lower()
    if "width=device-width" not in viewport or "user-scalable" in viewport or "maximum-scale" in viewport:
        issues.append("W-VIEWPORT：viewport 必须包含 width=device-width，且不得限制缩放。")
    if not parser.favicon_href.lower().startswith("data:image/svg+xml"):
        issues.append("W-FAVICON：页面必须使用内联 SVG favicon。")
    if parser.generator.strip().lower() != "cecemate":
        issues.append("W-GENERATOR：meta generator 必须为 CeCeMate。")
    if not parser.header_logo or not parser.footer_logo:
        issues.append("W-LOGO：页头和页脚必须使用带 alt 的 assets/logo.png。")
    if parser.has_iframe:
        issues.append("W-IFRAME：交付页面不得包含 iframe。")
    if parser.has_form:
        issues.append("W-FORM：交付页面不得包含表单提交。")
    if any(source.startswith(("http://", "https://")) and source not in ALLOWED_EXTERNAL_SCRIPTS for source in parser.script_sources):
        issues.append("W-EXTERNAL-SCRIPT：仅允许规定的 ECharts CDN 外部脚本。")
    disclaimer_ok = bool(parser.main_sections) and "disclaimer" in parser.main_sections[-1][0].get("class", "").split() and DISCLAIMER in parser.main_sections[-1][1]
    if not disclaimer_ok:
        issues.append("W-DISCLAIMER：main 的最后一个 section 必须是包含完整免责声明的 .disclaimer。")
    missing_tokens = sorted(REQUIRED_TOKENS - _root_tokens(parser.styles))
    if missing_tokens:
        issues.append(f"W-TOKENS：缺少必需的 :root 设计令牌：{', '.join(missing_tokens)}。")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 CeCeMate HTML 页面的核心结构。")
    parser.add_argument("page", type=Path, help="待检查的 HTML 文件")
    args = parser.parse_args()
    issues = validate(args.page)
    if issues:
        print("HTML 检查未通过：", file=sys.stderr)
        print("\n".join(f"- {issue}" for issue in issues), file=sys.stderr)
        return 1
    print("HTML 核心结构检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
