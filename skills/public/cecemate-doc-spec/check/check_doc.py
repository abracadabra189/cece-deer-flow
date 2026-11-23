#!/usr/bin/env python3
"""检查 CeCeMate DOCX 交付物的核心结构约束。"""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
DISCLAIMER = "内容由 AI 生成，请核实重要信息"
MAX_MEMBERS = 200
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
PAGE_SIZE = (11906, 16838)
PAGE_MARGIN = (1361, 1361, 1083, 1083)
TOLERANCE = 20


def _part_path(parent: str, target: str) -> str | None:
    """解析内部 OPC 关系目标，并拒绝路径穿越。"""
    if not target or target.startswith("/") or "://" in target:
        return None
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(parent), target))
    if resolved.startswith("../"):
        return None
    return resolved


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except (KeyError, ET.ParseError):
        return None


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    rel_part = posixpath.join(posixpath.dirname(part), "_rels", f"{posixpath.basename(part)}.rels")
    rels = _xml(archive, rel_part)
    if rels is None:
        return {}
    return {
        relation.attrib.get("Id", ""): (relation.attrib.get("Type", ""), relation.attrib.get("Target", ""))
        for relation in rels.findall(f"{REL}Relationship")
    }


def _is_safe_archive(archive: zipfile.ZipFile) -> bool:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        return False
    total = 0
    for info in infos:
        if info.file_size > MAX_MEMBER_BYTES:
            return False
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            return False
    return True


def _contains_packaged_logo(archive: zipfile.ZipFile, header_part: str, expected_hash: bytes) -> bool:
    relationships = _relationships(archive, header_part)
    header = _xml(archive, header_part)
    if header is None:
        return False
    for image in header.findall(f".//{A}blip"):
        rel_id = image.attrib.get(f"{R}embed")
        relation = relationships.get(rel_id or "")
        if relation is None or not relation[0].endswith("/image"):
            continue
        media_part = _part_path(header_part, relation[1])
        if media_part is None:
            continue
        try:
            if hashlib.sha256(archive.read(media_part)).digest() == expected_hash:
                return True
        except KeyError:
            continue
    return False


def _referenced_parts(document: ET.Element, relationships: dict[str, tuple[str, str]], kind: str) -> list[str]:
    parts: list[str] = []
    for node in document.findall(f".//{W}{kind}Reference"):
        relation = relationships.get(node.attrib.get(f"{R}id", ""))
        if relation is None or not relation[0].endswith(f"/{kind}"):
            continue
        part = _part_path("word/document.xml", relation[1])
        if part is not None:
            parts.append(part)
    return parts


def _has_page_field(archive: zipfile.ZipFile, footer_parts: list[str]) -> bool:
    for footer_part in footer_parts:
        footer = _xml(archive, footer_part)
        if footer is None:
            continue
        has_begin = any(node.attrib.get(f"{W}fldCharType") == "begin" for node in footer.findall(f".//{W}fldChar"))
        has_page = any("PAGE" in "".join(node.itertext()).upper() for node in footer.findall(f".//{W}instrText"))
        if has_begin and has_page:
            return True
    return False


def _within(value: str | None, expected: int) -> bool:
    try:
        return abs(int(value or "") - expected) <= TOLERANCE
    except ValueError:
        return False


def validate(path: Path) -> list[str]:
    """返回核心规则违反项；空列表表示通过。"""
    if path.suffix.lower() != ".docx" or not path.is_file():
        return ["D-PACKAGE：请提供存在的 .docx 文件。"]

    try:
        with zipfile.ZipFile(path) as archive:
            if not _is_safe_archive(archive):
                return ["D-PACKAGE：DOCX 压缩包超过安全检查限制。"]
            document = _xml(archive, "word/document.xml")
            if document is None:
                return ["D-PACKAGE：缺少或无法解析 word/document.xml。"]

            issues: list[str] = []
            body = document.find(f"{W}body")
            paragraphs = ["".join(paragraph.itertext()).strip() for paragraph in (body.findall(f"{W}p") if body is not None else [])]
            nonempty_paragraphs = [paragraph for paragraph in paragraphs if paragraph]
            document_text = "".join(document.itertext())
            if document_text.count(DISCLAIMER) != 1 or not nonempty_paragraphs or nonempty_paragraphs[-1] != DISCLAIMER:
                issues.append("D-DISCLAIMER：免责声明必须仅出现一次，且为正文最后一个非空段落。")

            page_section = document.find(f".//{W}sectPr")
            page_size = page_section.find(f"{W}pgSz") if page_section is not None else None
            page_margin = page_section.find(f"{W}pgMar") if page_section is not None else None
            if page_size is None or page_margin is None or not (
                _within(page_size.attrib.get(f"{W}w"), PAGE_SIZE[0])
                and _within(page_size.attrib.get(f"{W}h"), PAGE_SIZE[1])
                and _within(page_margin.attrib.get(f"{W}top"), PAGE_MARGIN[0])
                and _within(page_margin.attrib.get(f"{W}bottom"), PAGE_MARGIN[1])
                and _within(page_margin.attrib.get(f"{W}left"), PAGE_MARGIN[2])
                and _within(page_margin.attrib.get(f"{W}right"), PAGE_MARGIN[3])
            ):
                issues.append("D-PAGE：文档必须使用规定的 A4 页面尺寸和页边距。")

            relationships = _relationships(archive, "word/document.xml")
            expected_hash = hashlib.sha256((Path(__file__).resolve().parents[1] / "assets" / "logo.png").read_bytes()).digest()
            header_parts = _referenced_parts(document, relationships, "header")
            if not any(_contains_packaged_logo(archive, header_part, expected_hash) for header_part in header_parts):
                issues.append("D-LOGO：必须在被引用的页眉中嵌入本技能提供的 CeCeMate Logo。")

            if not _has_page_field(archive, _referenced_parts(document, relationships, "footer")):
                issues.append("D-PAGE-FIELD：被引用的页脚必须包含 PAGE 页码域。")

            for index, table in enumerate(document.findall(f".//{W}tbl"), start=1):
                layout = table.find(f"./{W}tblPr/{W}tblLayout")
                grid_columns = table.findall(f"./{W}tblGrid/{W}gridCol")
                if layout is None or layout.attrib.get(f"{W}type") != "fixed" or not grid_columns:
                    issues.append(f"D-TABLE-{index}：表格必须使用 fixed 布局和 tblGrid 列宽。")
    except (OSError, zipfile.BadZipFile):
        return ["D-PACKAGE：无法读取 DOCX 压缩包。"]
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 CeCeMate DOCX 文档的核心结构。")
    parser.add_argument("document", type=Path, help="待检查的 DOCX 文件")
    args = parser.parse_args()
    issues = validate(args.document)
    if issues:
        print("DOCX 检查未通过：", file=sys.stderr)
        print("\n".join(f"- {issue}" for issue in issues), file=sys.stderr)
        return 1
    print("DOCX 核心结构检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
