#!/usr/bin/env python3
"""生成 CeCeMate DOCX 模板。

模板只负责固定品牌与版式：封面 Logo、正文页眉 Logo、页脚 PAGE 域、
篇尾免责声明和命名样式。正文内容由 render_docx.py 插入到免责声明之前。

用法：
    python scripts/build_doc_template.py [--output templates/doc.docx]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOGO = ROOT / "assets" / "logo.png"
DEFAULT_OUTPUT = ROOT / "templates" / "doc.docx"
DISCLAIMER = "内容由 AI 生成，请核实重要信息"

COLOR_TEXT = RGBColor(0x3F, 0x44, 0x49)
COLOR_MUTED = RGBColor(0x7B, 0x83, 0x8C)
COLOR_CAPTION = RGBColor(0x62, 0x6A, 0x71)
COLOR_DISCLAIMER = RGBColor(0x28, 0x2B, 0x2E)
COLOR_BLUE_800 = RGBColor(0x00, 0x43, 0xA0)
COLOR_BLUE_700 = RGBColor(0x00, 0x4F, 0xC1)
COLOR_BLUE_600 = RGBColor(0x01, 0x6A, 0xDE)
COLOR_WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _remove_theme_fonts(rpr) -> None:
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        return
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)


def _set_rfonts(rpr, *, east: str, ascii_: str) -> None:
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), ascii_)
    rfonts.set(qn("w:hAnsi"), ascii_)
    rfonts.set(qn("w:eastAsia"), east)
    _remove_theme_fonts(rpr)


def _set_style_font(style, *, east: str, ascii_: str, size: float, bold: bool, color: RGBColor) -> None:
    style.font.name = ascii_
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    _set_rfonts(rpr, east=east, ascii_=ascii_)


def _set_run_font(run, *, east: str, ascii_: str, size: float, bold: bool, color: RGBColor) -> None:
    run.font.name = ascii_
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    _set_rfonts(rpr, east=east, ascii_=ascii_)


def _set_first_line_chars(paragraph_format, chars: int = 200, twips: int = 420) -> None:
    ppr = paragraph_format.element.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        ppr.append(ind)
    ind.set(qn("w:firstLineChars"), str(chars))
    ind.set(qn("w:firstLine"), str(twips))


def _set_bottom_border(paragraph, *, size_eighths: int = 4, color: str = "E0E6EB") -> None:
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = ppr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = OxmlElement("w:pBdr")
        ppr.append(pbdr)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size_eighths))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)


def _set_top_border(paragraph, *, size_eighths: int = 4, color: str = "E0E6EB") -> None:
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = ppr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = OxmlElement("w:pBdr")
        ppr.append(pbdr)
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), str(size_eighths))
    top.set(qn("w:space"), "12")
    top.set(qn("w:color"), color)
    pbdr.append(top)


def _add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(separate)
    run._r.append(text)
    run._r.append(end)


def _add_toc_field(paragraph) -> None:
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    paragraph.add_run()._r.append(begin)

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    paragraph.add_run()._r.append(instr)

    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    paragraph.add_run()._r.append(separate)

    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    paragraph.add_run()._r.append(end)


def _set_page(section) -> None:
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.4)
    section.bottom_margin = Cm(2.4)
    section.left_margin = Cm(1.91)
    section.right_margin = Cm(1.91)
    section.header_distance = Cm(1.2)
    section.footer_distance = Cm(1.4)


def _paragraph_style(styles, name: str):
    try:
        return styles[name]
    except KeyError:
        return styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)


def _add_styles(doc: Document) -> None:
    styles = doc.styles

    normal = styles["Normal"]
    _set_style_font(normal, east="宋体", ascii_="Arial", size=10.5, bold=False, color=COLOR_TEXT)
    normal.paragraph_format.line_spacing = Pt(17.3)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)

    body = _paragraph_style(styles, "Body Text")
    body.base_style = normal
    body.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    body.paragraph_format.line_spacing = Pt(17.3)
    body.paragraph_format.space_before = Pt(0)
    body.paragraph_format.space_after = Pt(6)
    _set_first_line_chars(body.paragraph_format)
    _set_style_font(body, east="宋体", ascii_="Arial", size=10.5, bold=False, color=COLOR_TEXT)

    cover_title = _paragraph_style(styles, "Cover Title")
    cover_title.base_style = normal
    cover_title.paragraph_format.line_spacing = 1.35
    cover_title.paragraph_format.space_before = Pt(0)
    cover_title.paragraph_format.space_after = Pt(0)
    _set_style_font(cover_title, east="黑体", ascii_="Arial", size=26, bold=True, color=COLOR_BLUE_800)

    cover_subtitle = _paragraph_style(styles, "Cover Subtitle")
    cover_subtitle.base_style = normal
    cover_subtitle.paragraph_format.line_spacing = 1.6
    cover_subtitle.paragraph_format.space_before = Pt(0)
    cover_subtitle.paragraph_format.space_after = Pt(0)
    _set_style_font(cover_subtitle, east="黑体", ascii_="Arial", size=14, bold=True, color=COLOR_BLUE_600)

    cover_meta = _paragraph_style(styles, "Cover Meta")
    cover_meta.base_style = normal
    cover_meta.paragraph_format.line_spacing = 1.9
    cover_meta.paragraph_format.space_before = Pt(0)
    cover_meta.paragraph_format.space_after = Pt(0)
    _set_style_font(cover_meta, east="宋体", ascii_="Arial", size=10.5, bold=False, color=COLOR_TEXT)

    heading1 = styles["Heading 1"]
    heading1.paragraph_format.line_spacing = 1.5
    heading1.paragraph_format.space_before = Pt(24)
    heading1.paragraph_format.space_after = Pt(10)
    heading1.paragraph_format.keep_with_next = True
    _set_style_font(heading1, east="黑体", ascii_="Arial", size=16, bold=True, color=COLOR_BLUE_700)

    heading2 = styles["Heading 2"]
    heading2.paragraph_format.line_spacing = 1.5
    heading2.paragraph_format.space_before = Pt(14)
    heading2.paragraph_format.space_after = Pt(6)
    heading2.paragraph_format.keep_with_next = True
    _set_style_font(heading2, east="黑体", ascii_="Arial", size=13, bold=True, color=COLOR_BLUE_600)

    heading3 = styles["Heading 3"]
    heading3.paragraph_format.line_spacing = 1.55
    heading3.paragraph_format.space_before = Pt(10)
    heading3.paragraph_format.space_after = Pt(4)
    heading3.paragraph_format.keep_with_next = True
    _set_style_font(heading3, east="黑体", ascii_="Arial", size=11.5, bold=True, color=COLOR_BLUE_600)

    toc_heading = _paragraph_style(styles, "TOC Heading")
    toc_heading.base_style = normal
    toc_heading.paragraph_format.line_spacing = 1.5
    toc_heading.paragraph_format.space_before = Pt(0)
    toc_heading.paragraph_format.space_after = Pt(10)
    _set_style_font(toc_heading, east="黑体", ascii_="Arial", size=16, bold=True, color=COLOR_BLUE_700)

    toc_entry = _paragraph_style(styles, "TOC Entry")
    toc_entry.base_style = normal
    toc_entry.paragraph_format.line_spacing = 1.5
    toc_entry.paragraph_format.space_before = Pt(0)
    toc_entry.paragraph_format.space_after = Pt(2)
    _set_style_font(toc_entry, east="宋体", ascii_="Arial", size=10.5, bold=False, color=COLOR_TEXT)

    caption = _paragraph_style(styles, "Caption")
    caption.base_style = normal
    caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.paragraph_format.line_spacing = 1.4
    caption.paragraph_format.space_before = Pt(6)
    caption.paragraph_format.space_after = Pt(6)
    caption.paragraph_format.keep_with_next = True
    _set_style_font(caption, east="黑体", ascii_="Arial", size=9, bold=True, color=COLOR_CAPTION)

    source = _paragraph_style(styles, "Source")
    source.base_style = normal
    source.paragraph_format.line_spacing = 1.5
    source.paragraph_format.space_before = Pt(0)
    source.paragraph_format.space_after = Pt(6)
    _set_style_font(source, east="宋体", ascii_="Arial", size=8.5, bold=False, color=COLOR_MUTED)

    table_text = _paragraph_style(styles, "Table Text")
    table_text.base_style = normal
    table_text.paragraph_format.line_spacing = 1.45
    table_text.paragraph_format.space_before = Pt(0)
    table_text.paragraph_format.space_after = Pt(0)
    _set_style_font(table_text, east="宋体", ascii_="Arial", size=9, bold=False, color=COLOR_TEXT)

    table_header = _paragraph_style(styles, "Table Header")
    table_header.base_style = normal
    table_header.paragraph_format.line_spacing = 1.45
    table_header.paragraph_format.space_before = Pt(0)
    table_header.paragraph_format.space_after = Pt(0)
    _set_style_font(table_header, east="黑体", ascii_="Arial", size=9, bold=True, color=COLOR_TEXT)

    disclaimer = _paragraph_style(styles, "Disclaimer")
    disclaimer.base_style = normal
    disclaimer.paragraph_format.line_spacing = 1.45
    disclaimer.paragraph_format.space_before = Pt(12)
    disclaimer.paragraph_format.space_after = Pt(0)
    _set_style_font(disclaimer, east="黑体", ascii_="Arial", size=9, bold=True, color=COLOR_DISCLAIMER)

    header_name = _paragraph_style(styles, "Header Doc Name")
    header_name.base_style = normal
    header_name.paragraph_format.line_spacing = 1.0
    header_name.paragraph_format.space_before = Pt(0)
    header_name.paragraph_format.space_after = Pt(0)
    _set_style_font(header_name, east="宋体", ascii_="Arial", size=9, bold=False, color=COLOR_MUTED)


def build(output: Path = DEFAULT_OUTPUT) -> Path:
    doc = Document()
    _add_styles(doc)

    cover = doc.sections[0]
    _set_page(cover)
    # 封面只保留大 Logo：显式断开并清空封面节的页眉/页脚。
    cover.header.is_linked_to_previous = False
    cover.footer.is_linked_to_previous = False
    for paragraph in cover.header.paragraphs:
        paragraph.text = ""
    for paragraph in cover.footer.paragraphs:
        paragraph.text = ""

    logo_paragraph = doc.add_paragraph()
    logo_paragraph.paragraph_format.line_spacing = 1.0
    logo_paragraph.paragraph_format.space_before = Pt(0)
    logo_paragraph.paragraph_format.space_after = Pt(0)
    logo_paragraph.add_run().add_picture(str(DEFAULT_LOGO), height=Cm(1.10))

    title = doc.add_paragraph("{{TITLE}}", style="Cover Title")
    title.paragraph_format.space_before = Pt(71)
    doc.add_paragraph("{{SUBTITLE}}", style="Cover Subtitle")
    meta = doc.add_paragraph("{{META}}", style="Cover Meta")
    meta.paragraph_format.space_before = Pt(57)
    date_version = doc.add_paragraph("{{DATE}}\t{{VERSION}}", style="Cover Meta")
    date_version.paragraph_format.space_before = Pt(330)
    date_version.paragraph_format.tab_stops.add_tab_stop(Cm(17.18), WD_TAB_ALIGNMENT.RIGHT)

    body = doc.add_section(WD_SECTION.NEW_PAGE)
    _set_page(body)
    body.header.is_linked_to_previous = False
    body.footer.is_linked_to_previous = False

    toc_title = doc.add_paragraph("目录", style="TOC Heading")
    toc_title.paragraph_format.space_before = Pt(0)
    toc_title.paragraph_format.space_after = Pt(10)
    doc.add_page_break()

    header = body.header.paragraphs[0]
    header.style = doc.styles["Header Doc Name"]
    header.paragraph_format.line_spacing = 1.0
    header.paragraph_format.space_before = Pt(0)
    header.paragraph_format.space_after = Pt(0)
    header.paragraph_format.tab_stops.add_tab_stop(Cm(17.18), WD_TAB_ALIGNMENT.RIGHT)
    logo_run = header.add_run()
    logo_run.add_picture(str(DEFAULT_LOGO), height=Cm(0.55))
    header.add_run("\t")
    name_run = header.add_run("{{DOC_NAME}}")
    _set_run_font(name_run, east="宋体", ascii_="Arial", size=9, bold=False, color=COLOR_MUTED)
    _set_bottom_border(header)

    footer = body.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.paragraph_format.line_spacing = 1.0
    footer.paragraph_format.space_before = Pt(0)
    footer.paragraph_format.space_after = Pt(0)
    _add_page_field(footer)
    for run in footer.runs:
        _set_run_font(run, east="宋体", ascii_="Arial", size=9, bold=False, color=COLOR_MUTED)

    pg_num_type = OxmlElement("w:pgNumType")
    pg_num_type.set(qn("w:start"), "1")
    body._sectPr.append(pg_num_type)

    # 模板可见占位：让人打开 doc.docx 时看到“正文区”和底部的免责声明，
    # 而不是把免责声明误读成页眉下方的一段。render_docx.py 会删除本段。
    placeholder = doc.add_paragraph(
        "{{CONTENT_PLACEHOLDER}} 正文内容占位：render_docx.py 会在此处插入实际内容。",
        style="Source",
    )
    placeholder.paragraph_format.space_before = Pt(0)
    placeholder.paragraph_format.space_after = Pt(610)
    placeholder.paragraph_format.first_line_indent = Cm(0)

    disclaimer = doc.add_paragraph(DISCLAIMER, style="Disclaimer")
    _set_top_border(disclaimer)

    # 让 Word 打开文档时更新 TOC/PAGE 等域。
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        update_fields = OxmlElement("w:updateFields")
        update_fields.set(qn("w:val"), "true")
        settings.append(update_fields)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 CeCeMate DOCX 模板")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    path = build(args.output)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
