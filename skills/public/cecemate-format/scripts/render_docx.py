#!/usr/bin/env python3
"""把 CeCeMate content.json 渲染为 DOCX。

模板固定封面 Logo、页眉 Logo、页脚 PAGE 域和篇尾免责声明；本脚本只把
结构化内容插入到免责声明之前，并对表格、图形和字体做规范落版。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, Twips
from naming import output_stem
from numbering import Numbering

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = ROOT / "brand-config.json"
DEFAULT_TEMPLATE = ROOT / "templates" / "doc.docx"
DISCLAIMER = "内容由 AI 生成，请核实重要信息"
CONTENT_TWIPS = 9739
TWIPS_PER_CM = 566.929


def _esc_text(value: object) -> str:
    return str(value)


def _replace_placeholders(doc: Document, values: dict[str, str]) -> None:
    def replace_in_paragraph(paragraph) -> None:
        for run in paragraph.runs:
            for key, value in values.items():
                if key in run.text:
                    run.text = run.text.replace(key, value)

    for paragraph in doc.paragraphs:
        replace_in_paragraph(paragraph)
    for section in doc.sections:
        for paragraph in section.header.paragraphs:
            replace_in_paragraph(paragraph)
        for paragraph in section.footer.paragraphs:
            replace_in_paragraph(paragraph)


def _cover_meta(meta: dict) -> str:
    lines = [
        f"报告主体：{meta.get('title') or '—'}",
        f"报告期：{meta.get('period') or '—'}",
        f"数据口径：{meta.get('scope') or '—'}",
        f"编制单位：{meta.get('author') or '—'}",
    ]
    return "\n".join(lines[:4])


class DocxRenderer:
    def __init__(self, content_path: Path, out_dir: Path, config: dict, template: Path, stem: str):
        self.content_path = content_path
        self.base = content_path.parent
        self.out_dir = out_dir
        self.config = config
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.docx_path = out_dir / f"{stem}.docx"
        self.figures_dir = out_dir / "figures"
        self.figures_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, self.docx_path)
        self.doc = Document(self.docx_path)
        self._anchor = None
        self._figure_index = 0
        self._numbering = Numbering()
        self._include_toc = False
        self._body_has_content = False
        self._chapter_page_break = True
        self._toc_items: list[tuple[int, str, str]] = []
        self._heading_index = 0

    def _find_anchor(self):
        for paragraph in list(self.doc.paragraphs):
            if "{{CONTENT_PLACEHOLDER}}" in paragraph.text:
                paragraph._p.getparent().remove(paragraph._p)
        if not self._include_toc:
            toc_title = next(
                (p for p in self.doc.paragraphs if p.style.name == "TOC Heading"),
                None,
            )
            if toc_title is not None:
                page_break = toc_title._p.getnext()
                toc_title._p.getparent().remove(toc_title._p)
                if page_break is not None and page_break.tag == qn("w:p"):
                    if any(br.attrib.get(qn("w:type")) == "page" for br in page_break.findall(f".//{qn('w:br')}")):
                        page_break.getparent().remove(page_break)
        for paragraph in self.doc.paragraphs:
            if paragraph.text.strip() == DISCLAIMER:
                self._anchor = paragraph._p
                return
        raise ValueError("模板缺少篇尾免责声明")

    def _insert_before_anchor(self, element) -> None:
        if self._anchor is None:
            raise RuntimeError("anchor 未初始化")
        self._anchor.addprevious(element)

    @staticmethod
    def _add_pageref(paragraph, bookmark: str) -> None:
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        begin.set(qn("w:dirty"), "true")
        paragraph.add_run()._r.append(begin)

        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = f" PAGEREF {bookmark} \\h "
        paragraph.add_run()._r.append(instr)

        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        paragraph.add_run()._r.append(separate)

        text = OxmlElement("w:t")
        text.text = "—"
        paragraph.add_run()._r.append(text)

        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        paragraph.add_run()._r.append(end)

    def _add_static_toc(self) -> None:
        title = next((p for p in self.doc.paragraphs if p.style.name == "TOC Heading"), None)
        if title is None:
            return
        cursor = title._p
        for level, text, bookmark in self._toc_items:
            paragraph = self.doc.add_paragraph(style="TOC Entry")
            cursor.addnext(paragraph._p)
            cursor = paragraph._p
            paragraph.paragraph_format.left_indent = Cm(0.6 * (level - 1))
            paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(17.18), WD_TAB_ALIGNMENT.RIGHT)
            paragraph.add_run(text)
            paragraph.add_run("\t")
            self._add_pageref(paragraph, bookmark)

    def _add_paragraph(self, text: str, style: str) -> None:
        paragraph = self.doc.add_paragraph(style=style)
        self._insert_before_anchor(paragraph._p)
        for index, chunk in enumerate(re.split(r"\n\s*\n", text)):
            if index:
                paragraph = self.doc.add_paragraph(style=style)
                self._insert_before_anchor(paragraph._p)
            self._add_inline(paragraph, chunk)

    def _add_inline(self, paragraph, text: str) -> None:
        position = 0
        for match in re.finditer(r"\*\*(.+?)\*\*", text):
            if match.start() > position:
                paragraph.add_run(text[position : match.start()])
            run = paragraph.add_run(match.group(1))
            run.bold = True
            position = match.end()
        if position < len(text):
            paragraph.add_run(text[position:])

    def _add_heading(self, level: int, text: str, numbered: bool = True) -> None:
        if level not in (1, 2, 3):
            raise ValueError("heading.level 只能是 1/2/3")
        if level == 1 and self._chapter_page_break and self._body_has_content:
            self._add_page_break()
        paragraph = self.doc.add_paragraph(style=f"Heading {level}")
        self._insert_before_anchor(paragraph._p)
        prefix = self._numbering.prefix(level) if numbered else ""
        paragraph.add_run(prefix + text)
        self._heading_index += 1
        if self._include_toc:
            bookmark = f"_TocCece{self._heading_index}"
            start = OxmlElement("w:bookmarkStart")
            start.set(qn("w:id"), str(self._heading_index))
            start.set(qn("w:name"), bookmark)
            end = OxmlElement("w:bookmarkEnd")
            end.set(qn("w:id"), str(self._heading_index))
            paragraph._p.insert(0, start)
            paragraph._p.append(end)
        self._body_has_content = True

    def _add_data_note(self, block: dict) -> None:
        lines = []
        for key, label in (("source", "来源"), ("scope", "口径"), ("period", "时间范围")):
            if block.get(key):
                lines.append(f"{label}：{block[key]}")
        limitations = block.get("limitations") or []
        if limitations:
            lines.append("已知局限：" + "；".join(str(item) for item in limitations))
        if lines:
            paragraph = self.doc.add_paragraph("；".join(lines), style="Source")
            self._insert_before_anchor(paragraph._p)

    def _add_list(self, items: list[str], ordered: bool) -> None:
        style = "List Number" if ordered else "List Bullet"
        for item in items:
            paragraph = self.doc.add_paragraph(style=style)
            self._insert_before_anchor(paragraph._p)
            self._add_inline(paragraph, str(item))

    def _add_callout(self, text: str) -> None:
        paragraph = self.doc.add_paragraph(style="Body Text")
        self._insert_before_anchor(paragraph._p)
        self._add_inline(paragraph, text)

    def _previous_is_page_break(self) -> bool:
        previous = self._anchor.getprevious() if self._anchor is not None else None
        if previous is None or previous.tag != qn("w:p"):
            return False
        ppr = previous.find(qn("w:pPr"))
        if ppr is not None and ppr.find(qn("w:pageBreakBefore")) is not None:
            return True
        return any(br.attrib.get(qn("w:type")) == "page" for br in previous.findall(f".//{qn('w:br')}"))

    def _add_page_break(self) -> None:
        if self._previous_is_page_break():
            return
        paragraph = self.doc.add_paragraph()
        self._insert_before_anchor(paragraph._p)
        run = paragraph.add_run()
        break_element = OxmlElement("w:br")
        break_element.set(qn("w:type"), "page")
        run._r.append(break_element)

    @staticmethod
    def _set_cell_width(cell, twips: int) -> None:
        tc_pr = cell._tc.get_or_add_tcPr()
        tc_w = tc_pr.find(qn("w:tcW"))
        if tc_w is None:
            tc_w = OxmlElement("w:tcW")
            tc_pr.append(tc_w)
        tc_w.set(qn("w:w"), str(twips))
        tc_w.set(qn("w:type"), "dxa")

    @staticmethod
    def _set_cell_shading(cell, fill: str) -> None:
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = tc_pr.find(qn("w:shd"))
        if shd is None:
            shd = OxmlElement("w:shd")
            tc_pr.append(shd)
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)

    @staticmethod
    def _set_cell_margins(table) -> None:
        tbl_pr = table._tbl.tblPr
        mar = tbl_pr.find(qn("w:tblCellMar"))
        if mar is None:
            mar = OxmlElement("w:tblCellMar")
            tbl_pr.append(mar)
        for side, twips in (("top", 40), ("bottom", 40), ("left", 80), ("right", 80)):
            node = mar.find(qn(f"w:{side}"))
            if node is None:
                node = OxmlElement(f"w:{side}")
                mar.append(node)
            node.set(qn("w:w"), str(twips))
            node.set(qn("w:type"), "dxa")

    @staticmethod
    def _set_table_borders(table) -> None:
        tbl_pr = table._tbl.tblPr
        borders = tbl_pr.find(qn("w:tblBorders"))
        if borders is None:
            borders = OxmlElement("w:tblBorders")
            tbl_pr.append(borders)
        specs = {
            "top": (6, "B3BBC3"),
            "left": (6, "B3BBC3"),
            "bottom": (6, "B3BBC3"),
            "right": (6, "B3BBC3"),
            "insideH": (4, "E0E6EB"),
            "insideV": (4, "E0E6EB"),
        }
        for side, (size, color) in specs.items():
            node = borders.find(qn(f"w:{side}"))
            if node is None:
                node = OxmlElement(f"w:{side}")
                borders.append(node)
            node.set(qn("w:val"), "single" if size else "nil")
            node.set(qn("w:sz"), str(size or 0))
            node.set(qn("w:space"), "0")
            node.set(qn("w:color"), color)

    @staticmethod
    def _set_table_layout(table) -> None:
        tbl_pr = table._tbl.tblPr
        layout = tbl_pr.find(qn("w:tblLayout"))
        if layout is None:
            layout = OxmlElement("w:tblLayout")
            tbl_pr.append(layout)
        layout.set(qn("w:type"), "fixed")
        tbl_w = tbl_pr.find(qn("w:tblW"))
        if tbl_w is None:
            tbl_w = OxmlElement("w:tblW")
            tbl_pr.append(tbl_w)
        tbl_w.set(qn("w:w"), str(CONTENT_TWIPS))
        tbl_w.set(qn("w:type"), "dxa")

    @staticmethod
    def _set_row_flags(row, *, header: bool = False) -> None:
        tr_pr = row._tr.get_or_add_trPr()
        if header and tr_pr.find(qn("w:tblHeader")) is None:
            tr_pr.append(OxmlElement("w:tblHeader"))
        if tr_pr.find(qn("w:cantSplit")) is None:
            tr_pr.append(OxmlElement("w:cantSplit"))

    def _add_table(self, block: dict) -> None:
        caption = block.get("caption")
        source = block.get("source")
        columns = block.get("columns") or []
        rows = block.get("rows") or []
        if not caption or not source:
            raise ValueError("table 必须包含 caption 和 source")
        if not columns:
            raise ValueError("table 缺少 columns")
        for row in rows:
            if len(row) != len(columns):
                raise ValueError("table 每行单元格数必须与 columns 一致")

        if self.config.get("doc", {}).get("tables", {}).get("require_width_cm") and any(column.get("width_cm") is None for column in columns):
            raise ValueError("DOCX 表格必须为每列提供 width_cm")
        widths_cm = [float(column.get("width_cm") or 0) for column in columns]
        if not any(widths_cm):
            widths_cm = [17.18 / len(columns)] * len(columns)
        scale = 17.18 / sum(widths_cm)
        widths = [round(width * scale * TWIPS_PER_CM) for width in widths_cm]
        widths[-1] += CONTENT_TWIPS - sum(widths)

        caption_paragraph = self.doc.add_paragraph(caption, style="Caption")
        self._insert_before_anchor(caption_paragraph._p)

        table = self.doc.add_table(rows=1, cols=len(columns))
        self._insert_before_anchor(table._tbl)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        self._set_table_layout(table)
        self._set_cell_margins(table)
        self._set_table_borders(table)
        for index, width in enumerate(widths):
            table.columns[index].width = Twips(width)

        header_cells = table.rows[0].cells
        for index, column in enumerate(columns):
            cell = header_cells[index]
            self._set_cell_width(cell, widths[index])
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            self._set_cell_shading(cell, "FBFBFC")
            paragraph = cell.paragraphs[0]
            paragraph.style = self.doc.styles["Table Header"]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT if column.get("align") == "right" else WD_ALIGN_PARAGRAPH.LEFT
            paragraph.add_run(_esc_text(column.get("label", "")))
        self._set_row_flags(table.rows[0], header=True)

        for row_values in rows:
            row = table.add_row()
            self._set_row_flags(row)
            for index, (column, value) in enumerate(zip(columns, row_values, strict=False)):
                cell = row.cells[index]
                self._set_cell_width(cell, widths[index])
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                paragraph = cell.paragraphs[0]
                paragraph.style = self.doc.styles["Table Text"]
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT if column.get("align") == "right" else WD_ALIGN_PARAGRAPH.LEFT
                paragraph.add_run(_esc_text(value))

        source_paragraph = self.doc.add_paragraph(source, style="Source")
        self._insert_before_anchor(source_paragraph._p)

    def _svg_to_png(self, source: Path) -> Path:
        self._figure_index += 1
        target = self.figures_dir / f"figure-{self._figure_index:02d}.png"
        try:
            import fitz

            document = fitz.open(str(source))
            page = document[0]
            pixmap = page.get_pixmap(dpi=300)
            pixmap.save(str(target))
            return target
        except Exception:
            try:
                import cairosvg

                cairosvg.svg2png(url=str(source), write_to=str(target), scale=3)
                return target
            except Exception as exc:
                raise ValueError(f"无法将 SVG 转为 PNG：{source.name}：{exc}") from exc

    def _natural_width_cm(self, path: Path) -> float:
        try:
            if path.suffix.lower() == ".svg":
                import fitz

                document = fitz.open(str(path))
                width_pt = float(document[0].rect.width)
                return width_pt * 2.54 / 72.0
            from PIL import Image

            image = Image.open(path)
            dpi = image.info.get("dpi", (96, 96))
            horizontal_dpi = float(dpi[0] or 96)
            return image.width / horizontal_dpi * 2.54
        except Exception:
            return 17.18

    def _add_figure(self, block: dict) -> None:
        src = block.get("src")
        caption = block.get("caption")
        source = block.get("source")
        if not src or not caption or not source:
            raise ValueError("figure 必须包含 src、caption 和 source")
        path = (self.base / src).resolve()
        if self.base.resolve() not in path.parents and path != self.base.resolve():
            raise ValueError(f"图形路径越界：{src}")
        if not path.is_file():
            raise ValueError(f"图形不存在：{src}")
        if path.suffix.lower() == ".svg":
            image_path = self._svg_to_png(path)
        elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            self._figure_index += 1
            image_path = self.figures_dir / f"figure-{self._figure_index:02d}{path.suffix.lower()}"
            shutil.copyfile(path, image_path)
        else:
            raise ValueError(f"不支持的图形格式：{path.suffix}")

        natural_width = self._natural_width_cm(path)
        requested_width = float(block.get("width_cm") or natural_width)
        width_cm = min(requested_width, natural_width, 17.18)
        paragraph = self.doc.add_paragraph()
        self._insert_before_anchor(paragraph._p)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.line_spacing = 1.0
        paragraph.paragraph_format.space_before = Pt(6)
        paragraph.paragraph_format.space_after = Pt(6)
        paragraph.add_run().add_picture(str(image_path), width=Cm(width_cm))

        caption_paragraph = self.doc.add_paragraph(caption, style="Caption")
        self._insert_before_anchor(caption_paragraph._p)
        source_paragraph = self.doc.add_paragraph(source, style="Source")
        self._insert_before_anchor(source_paragraph._p)

    def render(self, content: dict) -> Path:
        meta = content.get("meta") or {}
        if not meta.get("title"):
            raise ValueError("meta.title 必填")
        if not meta.get("date"):
            raise ValueError("meta.date 必填")
        blocks = content.get("blocks") or []
        self._include_toc = any(block.get("type") == "toc" for block in blocks)
        self._chapter_page_break = bool(meta.get("chapter_page_break", True))
        mode = str(meta.get("numbering") or "chapter")
        preview = Numbering(mode)
        self._toc_items = []
        heading_index = 0
        for block in blocks:
            if block.get("type") != "heading":
                continue
            heading_index += 1
            level = int(block.get("level", 1))
            text = str(block.get("text", ""))
            if block.get("numbered", True):
                text = preview.prefix(level) + text
            self._toc_items.append((level, text, f"_TocCece{heading_index}"))
        self._find_anchor()
        if self._include_toc:
            self._add_static_toc()
        self._numbering = Numbering(mode)
        title = str(meta["title"])
        _replace_placeholders(
            self.doc,
            {
                "{{TITLE}}": title,
                "{{SUBTITLE}}": str(meta.get("subtitle") or ""),
                "{{META}}": _cover_meta(meta),
                "{{DATE}}": str(meta["date"]),
                "{{VERSION}}": str(meta.get("version") or "v1.0"),
                "{{DOC_NAME}}": str(meta.get("header_title") or title)[:40],
            },
        )

        for block in blocks:
            kind = block.get("type")
            if kind == "heading":
                self._add_heading(
                    int(block.get("level", 1)),
                    str(block.get("text", "")),
                    bool(block.get("numbered", True)),
                )
            elif kind == "toc":
                # 静态目录已按模板 TOC 标题位置插入，内容里的 toc 只作为开关。
                pass
            elif kind == "paragraph":
                self._add_paragraph(str(block.get("text", "")), "Body Text")
            elif kind == "list":
                self._add_list(block.get("items") or [], bool(block.get("ordered")))
            elif kind == "table":
                self._add_table(block)
            elif kind == "figure":
                self._add_figure(block)
            elif kind == "data_note":
                self._add_data_note(block)
            elif kind == "page_break":
                self._add_page_break()
            elif kind == "callout":
                self._add_callout(str(block.get("text", "")))
            else:
                raise ValueError(f"未知 block type：{kind!r}")
            if kind not in {"page_break", "toc"}:
                self._body_has_content = True

        self.doc.save(self.docx_path)
        return self.docx_path


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 CeCeMate DOCX")
    parser.add_argument("content", type=Path, help="content.json")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args()

    try:
        content = json.loads(args.content.read_text(encoding="utf-8"))
        config = json.loads(args.config.read_text(encoding="utf-8"))
        stem = output_stem(content.get("meta") or {})
        renderer = DocxRenderer(args.content, args.out, config, args.template, stem)
        document = renderer.render(content)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DOCX 渲染失败：{exc}", file=sys.stderr)
        return 1

    if not args.skip_check:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "check_doc_required.py"), str(document)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr)
            return result.returncode
    print(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
