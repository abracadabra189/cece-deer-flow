#!/usr/bin/env python3
"""把 CeCeMate content.json 渲染为打印版 PDF（WeasyPrint）。

PDF 与 DOCX 使用同一份结构化内容，但不要求 DOCX→PDF 同源；两者各自按
CeCeMate 文档规范落版并各自校验。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import render_web
from naming import output_stem
from numbering import Numbering

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = ROOT / "brand-config.json"
DEFAULT_TEMPLATE = ROOT / "templates" / "print.html"
DISCLAIMER = "内容由 AI 生成，请核实重要信息"


def _css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3C ").replace(">", "\\3E ").replace("\n", " ")


def _print_vars(config: dict) -> str:
    web = config["web"]
    colors = web["colors"]
    lines: list[str] = []
    for name in ("600", "700", "800"):
        lines.append(f"    --blue-{name}: {colors['blue'][name]};")
    for name in ("300", "400", "500", "900", "1000", "1100", "1200"):
        lines.append(f"    --gray-{name}: {colors['gray'][name]};")
    lines.append(f"    --font-body: {web['page']['body_font_stack']};")
    return "\n".join(lines)


def _meta_html(meta: dict) -> str:
    lines = [
        f"报告主体：{meta.get('title') or '—'}",
        f"报告期：{meta.get('period') or '—'}",
        f"数据口径：{meta.get('scope') or '—'}",
        f"编制单位：{meta.get('author') or '—'}",
    ]
    return "<br>".join(render_web._esc(line) for line in lines[:4])


def _numbered_blocks(blocks: list[dict], mode: str) -> list[dict]:
    numbering = Numbering(mode)
    result: list[dict] = []
    for block in deepcopy(blocks):
        if block.get("type") == "heading":
            level = int(block.get("level", 1))
            if block.get("numbered", True):
                block["text"] = numbering.prefix(level) + str(block.get("text", ""))
        result.append(block)
    return result


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

    blocks = _numbered_blocks(content.get("blocks") or [], str(meta.get("numbering") or "chapter"))
    blocks, toc_entries = render_web.prepare_toc(blocks)
    body = render_web._blocks(blocks, content_path.parent, out_dir, config, toc_entries)

    template = template_path.read_text(encoding="utf-8")
    doc_name = _css_string(str(meta.get("header_title") or meta["title"])[:40])
    values = {
        "{{PRINT_VARS}}": _print_vars(config),
        "{{TITLE}}": render_web._esc(meta["title"]),
        "{{SUBTITLE}}": render_web._esc(meta.get("subtitle") or ""),
        "{{META}}": _meta_html(meta),
        "{{DATE}}": render_web._esc(meta["date"]),
        "{{VERSION}}": render_web._esc(meta.get("version") or "v1.0"),
        "{{DOC_NAME}}": doc_name,
        "{{CONTENT}}": body,
        "{{DISCLAIMER}}": render_web._esc(config["doc"]["disclaimer"]["text"]),
        "{{LOGO_SRC}}": "assets/logo.png",
    }
    for key, value in values.items():
        template = template.replace(key, value)

    stem = output_stem(meta)
    html_path = out_dir / f"{stem}.print.html"
    html_path.write_text(template, encoding="utf-8")

    from weasyprint import HTML

    pdf_path = out_dir / f"{stem}.pdf"
    HTML(filename=str(html_path), base_url=str(out_dir)).write_pdf(str(pdf_path))
    return pdf_path


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 CeCeMate PDF（WeasyPrint）")
    parser.add_argument("content", type=Path, help="content.json")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args()

    try:
        pdf = render(args.content, args.out, args.config, args.template)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PDF 渲染失败：{exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"PDF 渲染失败：缺少 WeasyPrint：{exc}", file=sys.stderr)
        return 1

    if not args.skip_check:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "check_pdf_required.py"), str(pdf)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr)
            return result.returncode
    print(pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
