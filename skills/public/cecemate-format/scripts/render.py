#!/usr/bin/env python3
"""按需渲染 CeCeMate 文档产物。

用法：
    python scripts/render.py content.json --out OUT                 # 默认只出 DOCX
    python scripts/render.py content.json --out OUT --formats docx
    python scripts/render.py content.json --out OUT --formats docx,pdf

HTML 由模型按网页规范直接生成，不经过此结构化渲染器。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FORMATS = ("docx", "pdf")
SCRIPTS = {
    "docx": "render_docx.py",
    "pdf": "render_pdf.py",
}


def parse_formats(raw: str) -> list[str]:
    requested = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not requested:
        raise ValueError("--formats 至少选择一个：docx、pdf；HTML 请按网页规范直接生成")
    unknown = sorted(set(requested) - set(FORMATS))
    if unknown:
        raise ValueError(f"未知格式：{', '.join(unknown)}")
    return [fmt for fmt in FORMATS if fmt in requested]


def main() -> int:
    parser = argparse.ArgumentParser(description="按需渲染 CeCeMate DOCX / PDF")
    parser.add_argument("content", type=Path, help="content.json")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument(
        "--formats",
        default="docx",
        help="逗号分隔：docx、pdf；默认只生成 docx；HTML 请直接生成完整页面",
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
