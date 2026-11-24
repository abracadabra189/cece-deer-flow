#!/usr/bin/env python3
"""CeCeMate DOCX 代码校验。

校验品牌与交付完整性：
- 封面 1.10cm Logo、正文页眉 0.55cm Logo，字节一致、比例 5.27:1；
- 免责短句全文仅一次，且是正文最后一个非空段落；页脚不得重复/隐藏；
- 模板占位符未残留；
- 无外链图片/对象、无 altChunk；
- 连续分页符之间没有内容（空白页的常见来源）。

页面尺寸、边距、字体、表格网格、页码域、分页效果等要求写在 SKILL.md 中，
由模板、渲染器和人工复核负责，脚本不拦截。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
DISCLAIMER = "内容由 AI 生成，请核实重要信息"
PLACEHOLDERS = {
    "{{TITLE}}",
    "{{SUBTITLE}}",
    "{{META}}",
    "{{DATE}}",
    "{{VERSION}}",
    "{{DOC_NAME}}",
    "{{CONTENT}}",
    "{{CONTENT_PLACEHOLDER}}",
}
EMU_TOLERANCE = 12000
COVER_CY = 396000
HEADER_CY = 198000
EXPECTED_RATIO = 2529 / 480
RATIO_TOLERANCE = 0.02
MAX_MEMBERS = 200
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024


def _part_path(parent: str, target: str) -> str | None:
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
        relation.attrib.get("Id", ""): (
            relation.attrib.get("Type", ""),
            relation.attrib.get("Target", ""),
        )
        for relation in rels.findall(f"{REL}Relationship")
    }


def _safe_archive(archive: zipfile.ZipFile) -> bool:
    total = 0
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        return False
    for info in infos:
        if info.file_size > MAX_MEMBER_BYTES:
            return False
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            return False
    return True


def _referenced_parts(
    document: ET.Element,
    relationships: dict[str, tuple[str, str]],
    kind: str,
) -> list[str]:
    parts: list[str] = []
    for node in document.findall(f".//{W}{kind}Reference"):
        relation = relationships.get(node.attrib.get(f"{R}id", ""))
        if relation is None or not relation[0].endswith(f"/{kind}"):
            continue
        part = _part_path("word/document.xml", relation[1])
        if part is not None:
            parts.append(part)
    return parts


def _drawings(
    archive: zipfile.ZipFile,
    part: str,
    element: ET.Element,
    relationships: dict[str, tuple[str, str]],
    expected_hash: str,
) -> Iterator[tuple[bool, int | None, int | None]]:
    for drawing in element.findall(f".//{W}drawing"):
        extent = drawing.find(f".//{WP}extent")
        cy = None
        cx = None
        if extent is not None:
            try:
                cy = int(extent.attrib.get("cy", ""))
                cx = int(extent.attrib.get("cx", ""))
            except ValueError:
                cy = None
                cx = None
        for blip in drawing.findall(f".//{A}blip"):
            relation = relationships.get(blip.attrib.get(f"{R}embed", ""))
            if relation is None or not relation[0].endswith("/image"):
                continue
            media = _part_path(part, relation[1])
            if media is None:
                continue
            try:
                digest = hashlib.sha256(archive.read(media)).hexdigest()
            except KeyError:
                continue
            yield digest == expected_hash, cy, cx


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(paragraph.itertext()).strip()


def _has_page_break(paragraph: ET.Element) -> bool:
    ppr = paragraph.find(f"{W}pPr")
    if ppr is not None and ppr.find(f"{W}pageBreakBefore") is not None:
        return True
    return any(br.attrib.get(f"{W}type") == "page" for br in paragraph.findall(f".//{W}br"))


def _has_blank_page(body: ET.Element) -> bool:
    """检测连续分页符之间没有内容的情况（空白页的常见来源）。"""
    seen_break = False
    content_since_break = False
    for child in body:
        if child.tag == f"{W}tbl":
            content_since_break = True
            continue
        if child.tag != f"{W}p":
            continue
        has_text = bool(_paragraph_text(child))
        has_object = any(child.find(f".//{W}{tag}") is not None for tag in ("drawing", "pict", "object"))
        has_content = has_text or has_object
        if _has_page_break(child):
            if seen_break and not content_since_break and not has_content:
                return True
            seen_break = True
            content_since_break = False
        elif has_content:
            content_since_break = True
    return False


def validate(path: Path, config_path: Path, *, allow_placeholders: bool = False) -> list[str]:
    if path.suffix.lower() != ".docx" or not path.is_file():
        return ["D-PACKAGE：请提供存在的 .docx 文件。"]
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        expected_hash = config["assets"]["logo"]["sha256"]
    except (OSError, KeyError, ValueError) as exc:
        return [f"D-CONFIG：无法读取 brand-config.json 的 logo.sha256：{exc}"]

    try:
        with zipfile.ZipFile(path) as archive:
            if not _safe_archive(archive):
                return ["D-PACKAGE：DOCX 压缩包超过安全检查限制。"]
            document = _xml(archive, "word/document.xml")
            if document is None:
                return ["D-PACKAGE：缺少或无法解析 word/document.xml。"]
            body = document.find(f"{W}body")
            if body is None:
                return ["D-PACKAGE：DOCX 缺少 body。"]
            relationships = _relationships(archive, "word/document.xml")
            issues: list[str] = []

            paragraphs = [p for p in body.findall(f"{W}p") if _paragraph_text(p)]
            document_text = "".join(document.itertext())
            if not allow_placeholders:
                remaining = sorted(marker for marker in PLACEHOLDERS if marker in document_text)
                if remaining:
                    issues.append(f"D-PLACEHOLDER：模板占位符未替换：{', '.join(remaining)}")
            if document_text.count(DISCLAIMER) != 1:
                issues.append("D-DISCLAIMER：免责声明必须仅出现一次。")
            if not paragraphs or _paragraph_text(paragraphs[-1]) != DISCLAIMER:
                issues.append("D-DISCLAIMER：免责声明必须是正文最后一个非空段落。")
            if _has_blank_page(body):
                issues.append("D-BLANK-PAGE：检测到连续分页符之间没有内容，可能产生空白页。")
            if paragraphs and any(run.find(f"{W}rPr/{W}vanish") is not None for run in paragraphs[-1].findall(f"{W}r")):
                issues.append("D-DISCLAIMER-HIDDEN：免责声明不得使用隐藏文字。")

            body_has_cover_logo = False
            for found, cy, cx in _drawings(archive, "word/document.xml", body, relationships, expected_hash):
                if found and cy and cx and abs(cy - COVER_CY) <= EMU_TOLERANCE:
                    body_has_cover_logo = True
                    if abs(cx / cy - EXPECTED_RATIO) / EXPECTED_RATIO > RATIO_TOLERANCE:
                        issues.append("D-LOGO-ASPECT：封面 Logo 不得拉伸，必须保持 5.27:1。")
            if not body_has_cover_logo:
                issues.append("D-LOGO-COVER：封面必须内嵌约 1.10cm 的 CeCeMate Logo。")

            header_has_logo = False
            for header_part in _referenced_parts(document, relationships, "header"):
                header_root = _xml(archive, header_part)
                if header_root is None:
                    continue
                header_rels = _relationships(archive, header_part)
                for found, cy, cx in _drawings(archive, header_part, header_root, header_rels, expected_hash):
                    if found and cy and cx and abs(cy - HEADER_CY) <= EMU_TOLERANCE:
                        header_has_logo = True
                        if abs(cx / cy - EXPECTED_RATIO) / EXPECTED_RATIO > RATIO_TOLERANCE:
                            issues.append("D-LOGO-ASPECT：页眉 Logo 不得拉伸，必须保持 5.27:1。")
            if not header_has_logo:
                issues.append("D-LOGO-HEADER：正文页眉必须内嵌约 0.55cm 的 CeCeMate Logo。")

            for name in archive.namelist():
                if not name.endswith(".rels"):
                    continue
                rels = _xml(archive, name)
                if rels is None:
                    continue
                for relation in rels.findall(f"{REL}Relationship"):
                    kind = relation.attrib.get("Type", "")
                    if relation.attrib.get("TargetMode") == "External" and kind.endswith(("/image", "/oleObject", "/package")):
                        issues.append("D-EXTERNAL：DOCX 不得引用外部图片/对象。")
                        break
            if body.find(f".//{W}altChunk") is not None:
                issues.append("D-EXTERNAL：DOCX 不得嵌入外部 HTML（altChunk）。")

            footer_parts = _referenced_parts(document, relationships, "footer")
            footer_text: list[str] = []
            for footer_part in footer_parts:
                footer_root = _xml(archive, footer_part)
                if footer_root is not None:
                    footer_text.append("".join(footer_root.itertext()))
            if DISCLAIMER in "".join(footer_text):
                issues.append("D-DISCLAIMER-FOOTER：页脚不得重复免责声明。")

            return issues
    except (OSError, zipfile.BadZipFile):
        return ["D-PACKAGE：无法读取 DOCX 压缩包。"]


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 CeCeMate DOCX 的 Logo 与免责声明。")
    parser.add_argument("document", type=Path, help="待检查的 DOCX 文件")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "brand-config.json",
        help="brand-config.json 路径（默认使用技能根目录）",
    )
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="检查模板本身时允许 {{...}} 占位符（渲染产物不要加这个参数）",
    )
    args = parser.parse_args()

    issues = validate(args.document, args.config, allow_placeholders=args.allow_placeholders)
    if issues:
        print("DOCX 检查未通过：", file=sys.stderr)
        print("\n".join(f"- {issue}" for issue in issues), file=sys.stderr)
        return 1
    print("DOCX Logo 与免责声明检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
