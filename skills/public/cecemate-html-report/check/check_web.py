#!/usr/bin/env python3
"""检查 CeCeMate HTML 交付物的核心结构约束。"""

from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path


DISCLAIMER = "内容由 AI 生成，请核实重要信息"
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class PageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.header_logo = False
        self.footer_logo = False
        self.main_sections: list[tuple[dict[str, str], str]] = []
        self._section_stack: list[tuple[dict[str, str], list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): (value or "") for key, value in attrs}
        if tag == "img" and attrs_dict.get("src", "").replace("\\", "/").endswith("assets/logo.png") and attrs_dict.get("alt", "").strip():
            if "header" in self.stack:
                self.header_logo = True
            if "footer" in self.stack:
                self.footer_logo = True

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

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._section_stack:
            attrs, text = self._section_stack.pop()
            self.main_sections.append((attrs, "".join(text)))
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break


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
    if not parser.header_logo or not parser.footer_logo:
        issues.append("W-LOGO：页头和页脚必须使用带 alt 的 assets/logo.png。")
    disclaimer_ok = bool(parser.main_sections) and "disclaimer" in parser.main_sections[-1][0].get("class", "").split() and DISCLAIMER in parser.main_sections[-1][1]
    if not disclaimer_ok:
        issues.append("W-DISCLAIMER：main 的最后一个 section 必须是包含完整免责声明的 .disclaimer。")
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
