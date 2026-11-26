"""S2b 归一化（本地 CECE MCP）：raw_mcp/*.json → data/*.json（报告 schema）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def pct(s):
    try:
        return round(float(str(s).replace("%", "")), 2)
    except (TypeError, ValueError):
        return 0.0


def data_of(doc):
    return (doc or {}).get("数据", doc) if isinstance(doc, dict) else doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    raw = rd / "raw_mcp"
    data_dir = rd / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    as_of, now = meta.get("as_of", ""), meta.get("fetched_at", "")
    out = {}

    def load(name):
        p = raw / f"{name}.json"
        if not p.exists():
            return None
        return data_of(json.loads(p.read_text(encoding="utf-8")))

    def put(name, rows, src):
        if rows:
            out[name] = {"dataset": name, "as_of": as_of, "source_cmd": src,
                         "fetched_at": now, "unit": "", "rows": rows}

    # score ← evaluation
    ev = load("evaluation") or {}
    dims_src = ev.get("score_dimensions") or []
    overall = next((d for d in dims_src if d.get("维度") == "综合"), None)
    if overall:
        grade_index = {"A": 4, "B": 3, "C": 2, "D": 1, "E": 0}.get(overall.get("等级"), 4)
        put("score", [{
            "total": overall.get("评分") if overall.get("评分") is not None else overall.get("分数"),
            "year": int(str(ev.get("year") or 0) or 0) or None,
            "grade": overall.get("等级"), "grade_index": grade_index,
            "rank_national": [overall.get("全国排名"), overall.get("全国同业数")],
            "rank_region": [overall.get("区域排名") if overall.get("区域排名") is not None else overall.get("地区排名"),
                            overall.get("区域同业数") if overall.get("区域同业数") is not None else overall.get("地区同业数")],
            "rank_national_label": "全国城市排名",
            "rank_region_label": f"{ev.get('region_name') or '区域'}排名",
            "dims": [{"name": d.get("维度"),
                      "score": d.get("评分") if d.get("评分") is not None else d.get("分数"),
                      "grade": d.get("等级")}
                     for d in dims_src if d.get("维度") != "综合"]}],
            "CECE MCP:get_industry_evaluation")

    # chain ← chain tree（chain_sequence 1/2/3 → 上/中/下游）
    ch = load("chain") or {}
    tree = ch.get("tree") or {}
    layers = tree.get("children") or []
    if layers:
        name_map = {1: "上游", 2: "中游", 3: "下游"}
        blocks = []
        for layer in layers:
            seq = layer.get("chain_sequence")
            blocks.append({
                "name": name_map.get(seq, layer.get("industry_name", "")),
                "count": layer.get("company_count"),
                "root": layer.get("industry_name", ""),
                "mids": [{"name": c.get("industry_name", ""),
                          "leaves": [x.get("industry_name", "") for x in (c.get("children") or [])]}
                         for c in (layer.get("children") or [])]})
        put("chain", [{"blocks": blocks}], "CECE MCP:get_industry_chain_tree")

    # portrait
    pt = load("portrait") or {}
    total = pt.get("company_total")

    def bins(items, ref):
        rows = [{"name": x.get("name") or "未分类", "count": x.get("count", 0), "share": pct(x.get("ratio"))} for x in items or []]
        if rows and ref:
            s = sum(r["count"] for r in rows)
            if 0 < s <= ref:
                for r in rows:
                    r["share"] = round(100.0 * r["count"] / ref, 2)
                if s < ref:
                    rows.append({"name": "其他/未分档", "count": ref - s, "share": round(100.0 * (ref - s) / ref, 2)})
        return rows

    put("ent_capital", bins(pt.get("capital_distribution"), total), "CECE MCP:get_industry_company_portrait")
    put("ent_age", bins(pt.get("age_distribution"), total), "CECE MCP:get_industry_company_portrait")

    stock, incr = pt.get("scale_trend_stock") or [], pt.get("scale_trend_increment") or []
    inc_by = {str(i.get("month")): sum(x.get("company_count", 0) or 0 for x in i.get("scale_items", [])) for i in incr}
    trend = []
    for s in stock:
        m = str(s.get("month"))
        trend.append({"period": m, "stock": sum(x.get("company_count", 0) or 0 for x in s.get("scale_items", [])),
                      "new_reg": inc_by.get(m, 0)})
    trend.sort(key=lambda r: r["period"])
    put("ent_trend", trend, "CECE MCP:get_industry_company_portrait")

    regions = sorted([{"name": x.get("region_name", ""), "total": x.get("company_count", 0),
                       "listed": None, "srme": None, "hightech": None}
                      for x in pt.get("region_distribution") or []], key=lambda r: -r["total"])[:10]
    put("ent_region", regions, "CECE MCP:get_industry_company_portrait")

    parks = []
    for i, x in enumerate((pt.get("park_distribution") or [])[:10]):
        ptot = x.get("park_total_company_count") or 0
        ent = x.get("company_count") or 0
        parks.append({"rank": i + 1, "name": x.get("park_name", ""), "region": "", "level": x.get("park_class", ""),
                      "park_total": ptot, "entered": ent,
                      "ratio": round(100.0 * ent / ptot, 2) if ptot else 0})
    put("parks", parks, "CECE MCP:get_industry_company_portrait")

    # innovation → patent_summary
    inv = load("innovation") or {}
    if inv.get("专利总量") is not None or inv.get("专利总数") is not None:
        types = {x.get("名称") or x.get("类型"): x.get("数量", 0) for x in inv.get("专利类型分布") or []}
        total = inv.get("专利总量") if inv.get("专利总量") is not None else inv.get("专利总数")
        put("patent_summary", [{
            "total": total, "fa": types.get("发明申请", 0), "sy": types.get("实用新型", 0),
            "wg": types.get("外观设计", 0), "fs": types.get("发明授权", 0),
            "parts_complete": sum(types.values()) == total,
            "year_new": inv.get("专利新增", 0), "year_new_fa": 0, "year_new_fs": 0, "year_new_sy": 0}],
            "CECE MCP:get_industry_innovation")

    # 融资
    fo = load("fin_overview") or {}
    put("fin_type", [{"name": x.get("financing_type", ""), "count": x.get("event_count", 0),
                      "share": round(float(x.get("share", 0) or 0) * 100, 2)}
                     for x in fo.get("by_financing_type") or []], "CECE MCP:get_industry_financing_overview")
    put("fin_region", sorted([{"name": x.get("region_name", ""), "count": x.get("event_count", 0),
                               "amount_wan": x.get("amount", 0)}
                              for x in fo.get("by_region") or []], key=lambda r: -r["count"])[:10],
        "CECE MCP:get_industry_financing_overview")
    if fo.get("event_count") is not None:
        put("fin_summary", [{"count": fo.get("event_count")}], "CECE MCP:get_industry_financing_overview")

    ft = load("fin_trend") or {}
    rows = []
    for y in ft.get("yearly_trend") or []:
        try:
            yr = int(y.get("year"))
        except (TypeError, ValueError):
            continue
        if 2015 <= yr <= 2100:
            rows.append({"year": yr, "amount_yi": round(float(y.get("amount", 0) or 0) / 1e4, 2),
                         "count": y.get("event_count", 0)})
    put("fin_trend", rows, "CECE MCP:get_industry_financing_trend")

    fe = load("fin_events") or {}
    evrows = []
    for i, e in enumerate(fe.get("events") or []):
        financiers = e.get("financiers") or []
        invs = e.get("investors") or []
        name = next((f.get("company") for f in financiers if f.get("company")), "—")
        evrows.append({"rank": i + 1, "name": name,
                       "amount_wan": float(e.get("amount") or 0), "round": e.get("sub_type") or "—",
                       "date": e.get("finance_date") or "—",
                       "investors": "、".join(x.get("company") or "" for x in invs[:4]) or "—"})
    put("fin_events", evrows, "CECE MCP:get_industry_financing_events")

    fi = load("fin_investors") or {}
    inst_rows = []
    for i, x in enumerate(fi.get("investors") or []):
        amt = float(x.get("invest_amount") or 0)
        unit = x.get("invest_amount_unit") or "元"
        yi = amt / 1e8 if unit == "元" else amt / 1e4
        inst_rows.append({"rank": i + 1, "name": x.get("investor_name", ""),
                          "stages": "、".join(x.get("stages") or []) or "—",
                          "count": x.get("event_count", 0), "amount_yi": round(yi, 2)})
    put("fin_inst", sorted(inst_rows, key=lambda r: -r["count"]), "CECE MCP:get_industry_financing_investors")

    # ent_top ← find_companies
    top = load("ent_top") or {}
    items = top.get("items") or top.get("企业列表") or []
    rows = []
    for i, it in enumerate(items):
        si = ((it.get("scoreInfo") or {}).get("valueScore") or {}).get("scoreValue")
        bi = it.get("basicInfo") or {}
        ri = it.get("regionInfo") or {}
        rows.append({"rank": i + 1, "name": it.get("companyName", ""),
                     "district": f"{ri.get('cityName', '')}/{ri.get('districtName', '')}".strip("/"),
                     "reg_cap": bi.get("registeredCapital") or "—",
                     "patents": None, "score": float(si) if si not in (None, "") else None})
    put("ent_top", rows, "CECE MCP:find_companies")

    # 平台不提供的展示点
    for name in ["ent_structure", "fin_index", "patent_trend", "patent_value", "patent_tech",
                 "patent_region", "patent_applicant", "fin_round"]:
        meta["limitations"].append({"dataset": name, "reason": "本地 CECE MCP 当前版本不提供该展示点（口径边界，非缺数）"})

    sources = {k: v["source_cmd"] for k, v in out.items()}
    manifest = {"as_of": as_of, "sources": sources, "limitations": [],
                "fetched_at": now, "source_mode": "mcp"}
    seen = set()
    for l in meta.get("limitations", []):
        k = (l.get("dataset"), l.get("reason"))
        if k not in seen:
            seen.add(k)
            manifest["limitations"].append(l)

    for name, doc in out.items():
        (data_dir / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_dir / "data_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"datasets": sorted(out), "limitations": len(manifest["limitations"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())