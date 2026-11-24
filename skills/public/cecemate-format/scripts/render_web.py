#!/usr/bin/env python3
"""把 CeCeMate content.json 渲染为单文件 HTML。

输入是结构化 JSON，图形只接受 SVG/PNG 文件；HTML 中的 SVG 会内联，
PNG 会复制到输出目录。模板固定页头/页脚 Logo 与篇尾免责声明。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from naming import output_stem

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = ROOT / "brand-config.json"
DEFAULT_TEMPLATE = ROOT / "templates" / "web.html"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _inline(text: str) -> str:
    escaped = _esc(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _css_vars(config: dict) -> str:
    web = config["web"]
    colors = web["colors"]
    lines: list[str] = []
    for name, value in colors["blue"].items():
        lines.append(f"    --blue-{name}: {value};")
    for name, value in colors["gray"].items():
        lines.append(f"    --gray-{name}: {value};")
    for name, value in colors["status"].items():
        lines.append(f"    --status-{name}: {value};")
    for index, value in enumerate(colors["chart"], start=1):
        lines.append(f"    --chart-{index}: {value};")
    for name, spec in web["typography"].items():
        key = name.replace("_", "-")
        lines.append(f"    --fs-{key}: {spec['px']}px;")
        lines.append(f"    --lh-{key}: {spec['line_height']};")
        lines.append(f"    --fw-{key}: {spec['weight']};")
    page = web["page"]
    layout = web["layout"]
    lines.extend(
        [
            f"    --content-max: {page['max_width_px']}px;",
            f"    --page-pad: {page['padding_x_px']}px;",
            f"    --section-gap: {page['section_gap_px']}px;",
            f"    --card-gap: {page['card_gap_px']}px;",
            f"    --font-heading: {page['font_stack']};",
            f"    --font-body: {page['body_font_stack']};",
            f"    --font-mono: {page['mono_font_stack']};",
            f"    --logo-header: {web['logo']['header_px']}px;",
            f"    --logo-footer: {web['logo']['footer_px']}px;",
            f"    --radius-tag: {layout['radius_px']['tag']}px;",
            f"    --radius-input: {layout['radius_px']['input']}px;",
            f"    --radius-card: {layout['radius_px']['card']}px;",
            f"    --radius-container: {layout['radius_px']['container']}px;",
            f"    --disclaimer-pad-top: {web['disclaimer']['padding_top_px']}px;",
            f"    --disclaimer-pad-bottom: {web['disclaimer']['padding_bottom_px']}px;",
        ]
    )
    return "\n".join(lines)


def _sanitize_svg(svg: str, index: int) -> str:
    lowered = svg.lower()
    if "<script" in lowered or "javascript:" in lowered:
        raise ValueError("SVG 包含脚本，已拒绝")
    if "foreignobject" in lowered:
        raise ValueError("SVG 包含 foreignObject，已拒绝")
    if re.search(r"\son[a-z]+\s*=", lowered):
        raise ValueError("SVG 包含事件属性，已拒绝")
    if re.search(r"(?:xlink:)?href\s*=\s*[\"'](?:https?:)?//", lowered):
        raise ValueError("SVG 包含外部引用，已拒绝")

    svg = re.sub(r"<\?xml[^>]*\?>", "", svg, flags=re.IGNORECASE).strip()
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg, flags=re.IGNORECASE).strip()
    if not svg.lower().startswith("<svg"):
        raise ValueError("图形文件不是 SVG")
    prefix = f"cecefig{index}-"
    ids = re.findall(r'\bid="([^"]+)"', svg)
    for old in ids:
        new = prefix + old
        svg = re.sub(rf'\bid="{re.escape(old)}"', f'id="{new}"', svg)
        svg = svg.replace(f"url(#{old})", f"url(#{new})")
        svg = svg.replace(f'href="#{old}"', f'href="#{new}"')
        svg = svg.replace(f'xlink:href="#{old}"', f'xlink:href="#{new}"')
    svg = re.sub(r"<svg\b([^>]*?)\swidth=\"[^\"]*\"", r"<svg\1", svg, count=1)
    svg = re.sub(r"<svg\b([^>]*?)\sheight=\"[^\"]*\"", r"<svg\1", svg, count=1)
    svg = re.sub(r"<svg\b", '<svg width="100%" height="auto"', svg, count=1)
    return svg


def _resolve_asset(src: str, base: Path) -> Path:
    path = (base / src).resolve()
    if base.resolve() not in path.parents and path != base.resolve():
        raise ValueError(f"图形路径越界：{src}")
    if not path.is_file():
        raise ValueError(f"图形不存在：{src}")
    return path


def _figure(block: dict, base: Path, out: Path, index: int, config: dict) -> str:
    src = block.get("src")
    if not src:
        raise ValueError("figure 缺少 src")
    path = _resolve_asset(str(src), base)
    caption = block.get("caption", "")
    source = block.get("source", "")
    if path.suffix.lower() == ".svg":
        svg = _sanitize_svg(path.read_text(encoding="utf-8"), index)
        graphic = svg
    elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        figure_dir = out / "figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        target = figure_dir / f"figure-{index:02d}{path.suffix.lower()}"
        shutil.copyfile(path, target)
        graphic = f'<img src="figures/{target.name}" alt="{_esc(caption or "图")}">'
    else:
        raise ValueError(f"不支持的图形格式：{path.suffix}")
    parts = ['<figure class="figure">', graphic]
    if caption:
        parts.append(f'<figcaption class="figure-caption">{_inline(caption)}</figcaption>')
    parts.append("</figure>")
    if source:
        parts.append(f'<p class="figure-source">{_inline(source)}</p>')
    return "\n".join(parts)


def _table(block: dict) -> str:
    caption = block.get("caption", "")
    source = block.get("source", "")
    columns = block.get("columns") or []
    rows = block.get("rows") or []
    if not columns:
        raise ValueError("table 缺少 columns")
    widths = [float(column.get("width_cm") or 1) for column in columns]
    total = sum(widths) or len(widths)
    percents = [width / total * 100 for width in widths]
    parts: list[str] = []
    if caption:
        parts.append(f'<div class="table-caption">{_inline(caption)}</div>')
    parts.append('<div class="table-wrap"><table class="data-table">')
    parts.append("<colgroup>" + "".join(f'<col style="width:{p:.3f}%">' for p in percents) + "</colgroup>")
    header_cells = []
    for column, percent in zip(columns, percents, strict=False):
        align = "num" if column.get("align") == "right" else "text"
        header_cells.append(f'<th class="{align}" style="width:{percent:.3f}%">{_inline(column.get("label", ""))}</th>')
    parts.append("<thead><tr>" + "".join(header_cells) + "</tr></thead><tbody>")
    for row in rows:
        cells = []
        for column, value in zip(columns, row, strict=False):
            align = "num" if column.get("align") == "right" else "text"
            cells.append(f'<td class="{align}">{_inline(value)}</td>')
        parts.append("<tr>" + "".join(cells) + "</tr>")
    parts.append("</tbody></table></div>")
    if source:
        parts.append(f'<p class="table-source">{_inline(source)}</p>')
    return "\n".join(parts)


def prepare_toc(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Give every heading an id and collect TOC entries in document order."""
    prepared: list[dict] = []
    entries: list[dict] = []
    heading_index = 0
    for block in blocks:
        item = dict(block)
        if item.get("type") == "heading":
            heading_index += 1
            item["_id"] = f"sec-{heading_index}"
            if item.get("numbered", True):
                entries.append(
                    {
                        "id": item["_id"],
                        "text": str(item.get("text", "")),
                        "level": int(item.get("level", 1)),
                    }
                )
        prepared.append(item)
    return prepared, entries


def _toc(block: dict, entries: list[dict]) -> str:
    title = _inline(block.get("title") or "目录")
    items = []
    for entry in entries:
        level = min(max(int(entry.get("level", 1)), 1), 3)
        items.append(f'<li class="toc-level-{level}"><a href="#{_esc(entry["id"])}">{_inline(entry["text"])}</a></li>')
    return f'<nav class="toc" aria-label="{title}"><div class="toc-title">{title}</div><ol class="toc-list">{"".join(items)}</ol></nav>'


def _tone(value: object) -> str:
    tone = str(value or "neutral")
    return tone if tone in {"info", "success", "danger", "warning", "todo", "neutral"} else "neutral"


def _tags(items: list[dict]) -> str:
    parts = []
    for item in items:
        text = item.get("text", "")
        parts.append(f'<li class="tag tag-{_tone(item.get("tone"))}">{_inline(text)}</li>')
    return f'<ul class="tags">{"".join(parts)}</ul>'


def _hero(block: dict) -> str:
    parts = ['<section class="hero">']
    if block.get("title"):
        parts.append(f'<h1 class="hero-title">{_inline(block["title"])}</h1>')
    if block.get("lead"):
        parts.append(f'<p class="hero-lead">{_inline(block["lead"])}</p>')
    chips = block.get("chips") or []
    if chips:
        parts.append('<ul class="meta-chips">' + "".join(f"<li>{_inline(chip)}</li>" for chip in chips) + "</ul>")
    if block.get("tags"):
        parts.append(_tags(block["tags"]))
    parts.append("</section>")
    return "\n".join(parts)


def _metrics(block: dict) -> str:
    cards = []
    for item in block.get("items") or []:
        unit = f'<span class="metric-unit">{_inline(item.get("unit"))}</span>' if item.get("unit") else ""
        tone = _tone(item.get("tone"))
        cards.append(
            '<div class="metric">'
            f'<div class="metric-label">{_inline(item.get("label", ""))}</div>'
            f'<div class="metric-value">{_inline(item.get("value", ""))}{unit}</div>'
            f'<div class="metric-change {tone}">{_inline(item.get("change", ""))}</div>'
            "</div>"
        )
    return f'<section class="metrics">{"".join(cards)}</section>'


def _conclusion(block: dict) -> str:
    paragraphs = "".join(f'<p class="paragraph">{_inline(text)}</p>' for text in block.get("paragraphs") or [])
    findings = "".join(f'<div class="finding-item"><span class="finding-number">{index:02d}</span><span>{_inline(item)}</span></div>' for index, item in enumerate(block.get("findings") or [], start=1))
    return (
        '<section class="conclusion-grid">'
        f'<div class="conclusion-main"><div class="conclusion-title">{_inline(block.get("title") or "综合研判")}</div>{paragraphs}</div>'
        f'<div class="findings"><div class="findings-title">{_inline(block.get("findings_title") or "关键发现")}</div>{findings}</div>'
        "</section>"
    )


def _matrix(block: dict) -> str:
    cards = []
    for item in block.get("items") or []:
        cards.append(
            '<div class="matrix-card">'
            f'<span class="tag tag-{_tone(item.get("tone"))}">{_inline(item.get("status") or "中性")}</span>'
            f'<div class="matrix-title">{_inline(item.get("title", ""))}</div>'
            f'<p class="matrix-text">{_inline(item.get("text", ""))}</p>'
            "</div>"
        )
    return f'<section class="matrix-grid">{"".join(cards)}</section>'


def _timeline(block: dict) -> str:
    items = []
    for item in block.get("items") or []:
        items.append(
            '<div class="timeline-item">'
            '<span class="timeline-dot" aria-hidden="true"></span>'
            f'<div class="timeline-date">{_inline(item.get("date", ""))}</div>'
            f'<div class="timeline-title">{_inline(item.get("title", ""))}</div>'
            f'<p class="timeline-text">{_inline(item.get("text", ""))}</p>'
            "</div>"
        )
    return f'<section class="timeline">{"".join(items)}</section>'


def _data_note(block: dict) -> str:
    lines = []
    for key, label in (("source", "来源"), ("scope", "口径"), ("period", "时间范围")):
        if block.get(key):
            lines.append(f"<div><strong>{label}：</strong>{_inline(block[key])}</div>")
    limitations = block.get("limitations") or []
    if limitations:
        lines.append("<div><strong>已知局限：</strong>" + "；".join(_inline(item) for item in limitations) + "</div>")
    return f'<section class="data-note">{"".join(lines)}</section>'


def _actions(block: dict) -> str:
    parts = []
    for item in block.get("items") or []:
        variant = "primary" if item.get("variant") == "primary" else "secondary"
        parts.append(f'<a class="btn btn-{variant}" href="{_esc(item.get("href") or "#")}">{_inline(item.get("label", ""))}</a>')
    return f'<div class="actions">{"".join(parts)}</div>'


def _blocks(
    blocks: list[dict],
    base: Path,
    out: Path,
    config: dict,
    toc_entries: list[dict] | None = None,
) -> str:
    rendered: list[str] = []
    figure_index = 0
    for block in blocks:
        kind = block.get("type")
        if kind == "heading":
            level = int(block.get("level", 1))
            if level not in (1, 2, 3):
                raise ValueError("heading.level 只能是 1/2/3")
            identifier = block.get("_id")
            id_attr = f' id="{_esc(identifier)}"' if identifier else ""
            rendered.append(f"<h{level}{id_attr}>{_inline(block.get('text', ''))}</h{level}>")
        elif kind == "toc":
            rendered.append(_toc(block, toc_entries or []))
        elif kind == "paragraph":
            rendered.append(f'<p class="paragraph">{_inline(block.get("text", ""))}</p>')
        elif kind == "list":
            tag = "ol" if block.get("ordered") else "ul"
            items = "".join(f"<li>{_inline(item)}</li>" for item in block.get("items", []))
            rendered.append(f'<{tag} class="list">{items}</{tag}>')
        elif kind == "table":
            rendered.append(_table(block))
        elif kind == "figure":
            figure_index += 1
            rendered.append(_figure(block, base, out, figure_index, config))
        elif kind == "page_break":
            rendered.append('<div class="page-break" aria-hidden="true"></div>')
        elif kind == "callout":
            tone = _tone(block.get("tone"))
            rendered.append(f'<div class="callout callout-{tone}">{_inline(block.get("text", ""))}</div>')
        elif kind == "hero":
            rendered.append(_hero(block))
        elif kind == "tags":
            rendered.append(_tags(block.get("items") or []))
        elif kind == "metrics":
            rendered.append(_metrics(block))
        elif kind == "chart_row":
            panels = []
            for key in ("primary", "secondary"):
                figure = block.get(key)
                if not isinstance(figure, dict):
                    continue
                figure_index += 1
                panels.append(f'<div class="chart-panel">{_figure(figure, base, out, figure_index, config)}</div>')
            if panels:
                rendered.append(f'<section class="chart-row">{"".join(panels)}</section>')
        elif kind == "conclusion":
            rendered.append(_conclusion(block))
        elif kind == "matrix":
            rendered.append(_matrix(block))
        elif kind == "timeline":
            rendered.append(_timeline(block))
        elif kind == "data_note":
            rendered.append(_data_note(block))
        elif kind == "actions":
            rendered.append(_actions(block))
        else:
            raise ValueError(f"未知 block type：{kind!r}")
    return "\n".join(rendered)


def render(content_path: Path, out_dir: Path, config_path: Path, template_path: Path) -> Path:
    content = json.loads(content_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    meta = content.get("meta") or {}
    if not meta.get("title"):
        raise ValueError("meta.title 必填")
    if not meta.get("date"):
        raise ValueError("meta.date 必填")

    out_dir.mkdir(parents=True, exist_ok=True)
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "assets" / "logo.png", assets / "logo.png")

    template = template_path.read_text(encoding="utf-8")
    header_bits = [meta.get("report_id"), meta.get("date")]
    header_meta = "　".join(str(bit) for bit in header_bits if bit)
    disclaimer = config["web"]["disclaimer"]
    blocks, toc_entries = prepare_toc(content.get("blocks") or [])
    body = _blocks(blocks, content_path.parent, out_dir, config, toc_entries)

    values = {
        "{{TITLE}}": _esc(meta["title"]),
        "{{CSS_VARS}}": _css_vars(config),
        "{{HEADER_META}}": _esc(header_meta),
        "{{CONTENT}}": body,
        "{{DISCLAIMER_SHORT}}": _esc(disclaimer["short"]),
        "{{DISCLAIMER_LONG}}": _esc(disclaimer["long"].replace("[页/报告]", "页面")),
        "{{FOOTER_SOURCE}}": _esc(meta.get("footer_source") or "CeCeMate 智能体生成"),
        "{{FOOTER_RIGHT}}": _esc(meta.get("version") or config["meta"]["spec_version"]),
        "{{LOGO_SRC}}": "assets/logo.png",
    }
    for key, value in values.items():
        template = template.replace(key, value)

    page = out_dir / f"{output_stem(meta)}.html"
    page.write_text(template, encoding="utf-8")
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 CeCeMate HTML")
    parser.add_argument("content", type=Path, help="content.json")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args()

    try:
        page = render(args.content, args.out, args.config, args.template)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"HTML 渲染失败：{exc}", file=sys.stderr)
        return 1

    if not args.skip_check:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "check_web_required.py"), str(page)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr)
            return result.returncode
    print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
