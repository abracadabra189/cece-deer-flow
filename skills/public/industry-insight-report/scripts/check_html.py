"""S4.5 HTML 检查：静态 lint + 可选 Playwright 无头度量。退出码 0=pass 1=fail。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    html_path, rd = Path(a.html), Path(a.run_dir)
    failures, checks = [], ["exists", "self_contained", "charts", "leak", "pages", "tables"]
    if not html_path.exists() or html_path.stat().st_size == 0:
        failures.append({"rule": "exists", "detail": "missing/empty"})
    text = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    if "</html>" not in text:
        failures.append({"rule": "exists", "detail": "no </html>"})
    for m in re.finditer(r'(?:src|href)="(http[^"]+)"', text):
        failures.append({"rule": "self_contained", "detail": m.group(1)[:80]})
    charts = json.loads((rd / "charts" / "charts.json").read_text(encoding="utf-8")) if (rd / "charts" / "charts.json").exists() else {}
    n_svg = text.count('role="img"')
    if n_svg != len(charts):
        failures.append({"rule": "charts", "detail": f"svg {n_svg} != charts {len(charts)}"})
    for bad in ("NaN", "undefined", ">None<"):
        if bad in text:
            failures.append({"rule": "leak", "detail": bad})
    n_page = text.count('class="page"')
    n_head = text.count('class="header"')
    n_foot = text.count('class="footer"')
    if n_page < 3 or n_head != n_page - 2 or n_foot != n_page - 2:
        failures.append({"rule": "pages", "detail": f"pages={n_page} header={n_head} footer={n_foot}"})
    n_table = text.count("<table>")
    n_thead = text.count("<thead>")
    if n_table != n_thead:
        failures.append({"rule": "tables", "detail": f"table {n_table} != thead {n_thead}"})
    # 可选无头度量
    measured = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(html_path.as_uri())
            measured = pg.eval_on_selector_all(
                ".page .content",
                "els => els.map(e => ({over: e.scrollHeight - e.clientHeight}))")
            b.close()
        for i, m in enumerate(measured):
            if m["over"] > 2:
                failures.append({"rule": "overflow", "detail": f"page {i + 1} over {m['over']}px"})
    except Exception:
        checks.append("headless_skipped")
    report = {"passed": not failures, "checks": checks, "failures": failures,
              "pages": n_page, "headless": measured is not None}
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "pages": n_page}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
