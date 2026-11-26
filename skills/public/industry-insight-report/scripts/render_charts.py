"""S4a 图表渲染：由 blocks.json 的 chart 计划 + data/ 构建 spec 并渲染内联 SVG。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charts_svg  # noqa: E402


def _rows(data, ds):
    return data.get(ds, {}).get("rows", [])


def build_spec(block, data, meta):
    t, ds = block["type"], block["dataset"]
    rows = _rows(data, ds)
    if t == "score_bar":
        r = rows[0]
        return {"type": t, "total": r["total"], "year": r.get("year"), "grade": r.get("grade"),
                "grade_index": r.get("grade_index", 4), "rank_national": r.get("rank_national"),
                "rank_region": r.get("rank_region"), "rank_national_label": r.get("rank_national_label"),
                "rank_region_label": r.get("rank_region_label"), "title": block["title"]}
    if t == "radar":
        return {"type": t, "dims": rows[0]["dims"]}
    if t == "tree":
        return {"type": t, "blocks": rows[0]["blocks"]}
    if t == "bar_grouped":
        return {"type": t, "categories": [str(r.get("period") or r.get("year")) for r in rows],
                "series": [{"name": "企业总数", "values": [r["stock"] for r in rows]},
                           {"name": "新注册企业数", "values": [r["new_reg"] for r in rows]}], "unit": "(家)"}
    if t == "pyramid":
        r = rows[0]
        lv = [
            {"name": "上市企业", "count": r.get("listed"), "share": r.get("listed_share") or 0},
            {"name": "专精特新企业", "count": r.get("srme"), "share": r.get("srme_share") or 0},
            {"name": "高新技术企业", "count": r.get("hightech"), "share": r.get("hightech_share") or 0},
            {"name": "全部在营企业", "count": r.get("total"), "share": 100.0},
        ]
        return {"type": t, "levels": [x for x in lv if x["count"] is not None]}
    if t == "donut":
        if ds == "patent_value":
            items = [{"name": f"{r['score']}分", "count": r["count"], "share": r.get("share", 0)}
                     for r in rows[0].get("dist", [])]
        else:
            items = [{"name": r["name"], "count": r.get("count", r.get("amount_wan", 0)),
                      "share": r.get("share", 0)} for r in rows]
        return {"type": t, "items": items, "center_label": block.get("center_label", ""),
                "center_value": block.get("center_value", ""), "unit_word": block.get("unit_word", "家")}
    if t == "hbar":
        key = block.get("value_key", "total")
        return {"type": t, "items": [{"name": r["name"], "value": r[key]} for r in rows]}
    if t == "bar_stacked":
        return {"type": t, "categories": [str(r["year"]) for r in rows],
                "series": [{"name": "发明申请", "values": [r["fa"] for r in rows]},
                           {"name": "实用新型", "values": [r["sy"] for r in rows]},
                           {"name": "外观设计", "values": [r["wg"] for r in rows]},
                           {"name": "发明授权", "values": [r["fs"] for r in rows]}], "unit": "(件)"}
    if t == "bubble_grid":
        m = rows[0]
        return {"type": t, "rows": m["dims_rows"], "cols": m["cols"], "matrix": m["matrix"]}
    if t == "dual_bar_line":
        return {"type": t, "categories": [str(r["year"]) for r in rows],
                "bars": {"name": "金额", "values": [r["amount_yi"] for r in rows]},
                "line": {"name": "件数", "values": [r["count"] for r in rows]},
                "unit_left": "(亿元)", "unit_right": "(次)"}
    if t == "line_index":
        return {"type": t, "categories": [str(r["year"]) for r in rows],
                "series": [{"name": "总营收水平指数", "values": [r["revenue_index"] for r in rows]},
                           {"name": "平均营收水平指数", "values": [r.get("asset_index") for r in rows]}]}
    raise ValueError(f"unknown chart type {t}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    blocks = json.loads((rd / "blocks.json").read_text(encoding="utf-8"))
    theme = json.loads((Path(__file__).resolve().parent.parent / "assets" / "theme.json")
                       .read_text(encoding="utf-8"))
    data = {}
    for p in (rd / "data").glob("*.json"):
        if p.name != "data_manifest.json":
            d = json.loads(p.read_text(encoding="utf-8"))
            data[d["dataset"]] = d
    manifest = json.loads((rd / "data" / "data_manifest.json").read_text(encoding="utf-8"))
    charts_dir = rd / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for b in blocks:
        if b["t"] != "chart":
            continue
        spec = build_spec(b, data, manifest)
        svg, h_mm = charts_svg.render(spec, theme)
        (charts_dir / f"{b['chart_id']}.svg").write_text(svg, encoding="utf-8")
        src = manifest.get("sources", {}).get(b["dataset"], "行业洞察")
        out[b["chart_id"]] = {"title": b["title"], "as_of": manifest.get("as_of", ""),
                              "source": src, "h_mm": round(h_mm, 1), "type": b["type"]}
    (charts_dir / "charts.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"charts": len(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
