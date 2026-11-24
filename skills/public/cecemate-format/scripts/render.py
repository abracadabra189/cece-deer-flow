#!/usr/bin/env python3
"""按需渲染 CeCeMate 产物，不默认生成三件套。

用法：
    python scripts/render.py content.json --out OUT                 # 默认只出 DOCX
    python scripts/render.py content.json --out OUT --formats docx
    python scripts/render.py content.json --out OUT --formats docx,html
    python scripts/render.py content.json --out OUT --formats html,docx,pdf  # 仅明确要求时
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FORMATS = ("html", "docx", "pdf")
SCRIPTS = {
    "html": "render_web.py",
    "docx": "render_docx.py",
    "pdf": "render_pdf.py",
}


def parse_formats(raw: str) -> list[str]:
    requested = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not requested:
        raise ValueError("--formats 至少选择一个：html、docx、pdf")
    unknown = sorted(set(requested) - set(FORMATS))
    if unknown:
        raise ValueError(f"未知格式：{', '.join(unknown)}")
    return [fmt for fmt in FORMATS if fmt in requested]


def main() -> int:
    parser = argparse.ArgumentParser(description="按需渲染 CeCeMate HTML / DOCX / PDF")
    parser.add_argument("content", type=Path, help="content.json")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument(
        "--formats",
        default="docx",
        help="逗号分隔：html、docx、pdf；默认只生成 docx",
    )
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args()

    try:
        formats = parse_formats(args.formats)
    except ValueError as exc:
        print(f"渲染失败：{exc}", file=sys.stderr)
        return 1

    for fmt in formats:
        command = [sys.executable, str(SCRIPT_DIR / SCRIPTS[fmt]), str(args.content), "--out", str(args.out)]
        if args.skip_check:
            command.append("--skip-check")
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr)
            return result.returncode
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
