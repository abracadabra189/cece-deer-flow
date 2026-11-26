"""S5 PDF 转换：Playwright 优先，WeasyPrint 回退；无引擎退出码 3（降级）。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _page_count(pdf: Path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf)).pages)
    except Exception:
        data = pdf.read_bytes()
        return len(re.findall(rb"/Type\s*/Page[^s]", data))


def _page2_text(pdf: Path):
    try:
        from pypdf import PdfReader
        return PdfReader(str(pdf)).pages[1].extract_text() or ""
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect-pages", type=int, default=0)
    a = ap.parse_args()
    html, out = Path(a.html), Path(a.out)
    engine = None
    known_pages = 0
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(html.as_uri())
            pg.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
            b.close()
        engine = "playwright"
    except Exception:
        try:
            from weasyprint import HTML
            rendered = HTML(filename=str(html)).render()
            known_pages = len(rendered.pages)
            rendered.write_pdf(str(out))
            engine = "weasyprint"
        except Exception:
            print(json.dumps({"degraded": True, "reason": "no pdf engine"}, ensure_ascii=False), file=sys.stderr)
            return 3
    checks = {"engine": engine, "pages": known_pages or _page_count(out)}
    ok = True
    if a.expect_pages and checks["pages"] != a.expect_pages:
        checks["page_mismatch"] = [checks["pages"], a.expect_pages]
        ok = False
    t2 = _page2_text(out)
    if t2 and "产业洞察报告" not in t2:
        checks["header_missing"] = True
        ok = False
    (out.parent / "pdf_check.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
