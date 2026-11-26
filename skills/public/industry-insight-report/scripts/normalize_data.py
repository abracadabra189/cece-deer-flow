"""S2b 归一化：raw/{industries,resolved,profile,parks}.json → data/*.json（报告 schema）。

平台口径边界（见 references/hydc-command-map.md）：聚合画像为精选子集，
ent_top/patent_value/patent_tech/patent_region/patent_applicant/fin_round/fin_events/fin_inst
等平台不直出的展示点登记为 limitation，章节按"数据暂缺"优雅跳过。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GRADE_INDEX = {"A": 4, "B": 3, "C": 2, "D": 1, "E": 0}
UNAVAILABLE = ["ent_top", "patent_value", "patent_tech", "patent_region",
               "patent_applicant", "fin_round", "fin_events", "fin_inst"]


def pct(s):
    try:
        return round(float(str(s).replace("%", "")), 2)
    except (TypeError, ValueError):
        return 0.0


def layer_name(name):
    if any(k in name for k in ("基础", "使能", "上游")):
        return "上游"
    if any(k in name for k in ("产品开发", "系统集成", "中游")):
        return "中游"
    if any(k in name for k in ("应用", "下游")):
        return "下游"
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    raw = rd / "raw"
    data_dir = rd / "data"
    manifest = json.loads((data_dir / "data_manifest.json").read_text(encoding="utf-8"))
    as_of = manifest.get("as_of", "")
    now = manifest.get("fetched_at", "")
    out = {}

    def put(name, rows, src):
        if rows:
            out[name] = {"dataset": name, "as_of": as_of, "source_cmd": src,
                         "fetched_at": now, "unit": "", "rows": rows}
            manifest["sources"][name] = "HYDC:" + src.split(" ")[0]

    profile_p = raw / "profile.json"
    g = {}
    if profile_p.exists():
        d = json.loads(profile_p.read_text(encoding="utf-8"))
        g = (d.get("result") or d).get("groups") or {}

    # score
    ev = (g.get("score") or {}).get("evaluateResult") or {}
    items = ev.get("itemList") or []
    overall = next((i for i in items if i.get("category") == "OVERALL"), None)
    if overall:
        dims = [{"name": i["categoryName"], "score": i["categoryScore"], "grade": i.get("categoryGrade", "")}
                for i in items if i.get("category") != "OVERALL"]
        put("score", [{
            "total": overall["categoryScore"], "year": int(ev.get("year") or 0) or None,
            "grade": overall.get("categoryGrade", ""), "grade_index": GRADE_INDEX.get(overall.get("categoryGrade"), 4),
            "rank_national": [overall.get("categoryRankInNation"), overall.get("categoryRankInNationTotal")],
            "rank_region": [overall.get("categoryRankInArea"), overall.get("categoryRankInAreaTotal")],
            "rank_national_label": "全国城市排名",
            "rank_region_label": f"{ev.get('areaName', '区域')}排名",
            "dims": dims}], "queryIndustryProfile --category score")

    # chain
    ind = (g.get("portrait") or {}).get("industryDistribution") or {}
    tops = ind.get("itemList") or []
    if tops:
        blocks = []
        for t in tops:
            blocks.append({
                "name": layer_name(t.get("industryName", "")), "count": t.get("companyCount"),
                "root": t.get("industryName", ""),
                "mids": [{"name": c.get("industryName", ""), "leaves": [x.get("industryName", "") for x in c.get("children", [])]}
                         for c in t.get("children", [])]})
        put("chain", [{"blocks": blocks}], "queryIndustryProfile --category portrait")

    # ent_trend（月度粒度）
    sc = (g.get("portrait") or {}).get("scaleChartBundle") or {}
    stock, incr = sc.get("stockItemList") or [], sc.get("incrItemList") or []
    rows = []
    for s in stock:
        inc = next((i for i in incr if i.get("time") == s.get("time")), None)
        rows.append({"period": s.get("time", ""),
                     "stock": sum(x.get("companyCount", 0) or 0 for x in s.get("scaleItemList", [])),
                     "new_reg": sum(x.get("companyCount", 0) or 0 for x in (inc or {}).get("scaleItemList", []))})
    rows.sort(key=lambda r: r["period"])
    put("ent_trend", rows, "queryIndustryProfile --category portrait")

    # ent_structure
    td = ((g.get("portrait") or {}).get("typeDistribution") or {}).get("itemList") or []
    if td:
        get = lambda *names: next((t["companyCount"] for t in td if any(n in t.get("typeName", "") for n in names)), None)  # noqa: E731
        total = get("全部") or 0
        listed, srme, ht = get("A股", "上市"), get("专精特新"), get("高新技术")
        row = {"total": total,
               "listed": listed, "listed_share": round(100.0 * listed / total, 2) if listed and total else None,
               "srme": srme, "srme_share": round(100.0 * srme / total, 2) if srme and total else None,
               "hightech": ht, "hightech_share": round(100.0 * ht / total, 2) if ht and total else None}
        put("ent_structure", [row], "queryIndustryProfile --category portrait")

    # ent_capital / ent_age（平台精选分档，覆盖不足时补"其他"档保持占比完整）
    pie = (g.get("portrait") or {}).get("pieChartBundle") or {}
    td_total = next((t.get("companyCount") for t in td if "全部" in t.get("typeName", "")), None) if td else None

    def _bins(items, ref):
        rows = [{"name": x.get("name", ""), "count": x.get("companyCount", 0), "share": pct(x.get("ratio"))} for x in items]
        if rows and ref:
            s = sum(r["count"] for r in rows)
            if 0 < s <= ref:
                for r in rows:  # 以总量重算占比，保证口径闭合
                    r["share"] = round(100.0 * r["count"] / ref, 2)
                if s < ref:
                    rows.append({"name": "其他/未分档", "count": ref - s, "share": round(100.0 * (ref - s) / ref, 2)})
        return rows

    put("ent_capital", _bins(pie.get("capitalItemList", []), td_total), "queryIndustryProfile --category portrait")
    put("ent_age", _bins(pie.get("ageItemList", []), td_total), "queryIndustryProfile --category portrait")

    # ent_region
    rd_ = (g.get("portrait") or {}).get("regionDistribution") or {}
    put("ent_region", [{"name": x.get("regionName", ""), "total": x.get("companyCount", 0),
                        "listed": None, "srme": None, "hightech": None}
                       for x in rd_.get("itemList", [])], "queryIndustryProfile --category portrait")

    # patent_summary / patent_trend
    pat = (g.get("ip") or {}).get("patent") or {}
    pstat = (g.get("portrait") or {}).get("patentStat") or {}
    years = pstat.get("items") or []
    trend = []
    for y in years:
        m = {i.get("key"): i.get("val", 0) for i in y.get("items", [])}
        trend.append({"year": int(y.get("year", 0)), "fa": m.get("发明申请", 0), "sy": m.get("实用新型", 0),
                      "wg": m.get("外观设计", 0), "fs": m.get("发明授权", 0)})
    trend.sort(key=lambda r: r["year"])
    put("patent_trend", trend, "queryIndustryProfile --category ip/portrait")
    if pat.get("count") is not None:
        sums = {k: sum(r[k] for r in trend) for k in ("fa", "sy", "wg", "fs")}
        last = trend[-1] if trend else {}
        put("patent_summary", [{
            "total": pat.get("count"), **sums,
            "parts_complete": sum(sums.values()) == pat.get("count"),
            "year_new": sum(last.get(k, 0) for k in ("fa", "sy", "wg", "fs")) if last else 0,
            "year_new_fa": last.get("fa", 0), "year_new_fs": last.get("fs", 0), "year_new_sy": last.get("sy", 0)}],
            "queryIndustryProfile --category ip")

    # fin_index
    fin = g.get("finance") or {}
    def series(key, want):
        tr = (fin.get(key) or {}).get("timeItemList") or []
        m = {}
        for t in tr:
            v = next((i.get("value") for i in t.get("indicatorItemList", []) if i.get("indicator") == want), None)
            if v is not None:
                m[int(t.get("year", 0))] = round(float(v), 2)
        return m
    rev, asset = series("allCompanyOperationTrend", "总营收水平指数"), series("allCompanyAssetTrend", "总资产水平指数")
    fy = sorted(set(rev) | set(asset))
    put("fin_index", [{"year": y, "revenue_index": rev.get(y), "asset_index": asset.get(y)} for y in fy],
        "queryIndustryProfile --category finance")

    # fin_trend / fin_summary / fin_type / fin_region
    inv = g.get("invest") or {}
    ft = [x for x in (inv.get("financeTrend") or {}).get("items", [])
          if str(x.get("year", "")).isdigit() and 1900 < int(x.get("year", 0)) < 2100]
    ft.sort(key=lambda x: int(x["year"]))
    frows = [{"year": int(x["year"]), "amount_yi": round(float(x.get("amount", 0) or 0) / 1e4, 2),
              "count": x.get("num", 0)} for x in ft]
    put("fin_trend", frows, "queryIndustryProfile --category invest")
    rf = inv.get("regionFinance") or {}
    if rf.get("num") is not None:
        s = {"count": rf.get("num")}
        if frows:
            s.update(amount_yi=round(sum(r["amount_yi"] for r in frows), 2),
                     active_year=max(frows, key=lambda r: r["count"])["year"],
                     active_count=max(r["count"] for r in frows),
                     top_year=max(frows, key=lambda r: r["amount_yi"])["year"],
                     top_amount_yi=max(r["amount_yi"] for r in frows),
                     last_year_count=frows[-1]["count"], last_year_amount_yi=frows[-1]["amount_yi"])
        put("fin_summary", [s], "queryIndustryProfile --category invest")
    tf = (inv.get("typeFinance") or {}).get("data") or []
    trows = sorted([{"name": x.get("type1", ""), "count": x.get("num", 0), "share": round(float(x.get("rate", 0) or 0), 2)}
                    for x in tf], key=lambda r: -r["count"])
    base = (out.get("fin_summary", {}).get("rows") or [{}])[0].get("last_year_count") if "fin_summary" in out else None
    if trows and base:
        s = sum(r["count"] for r in trows)
        if 0 < s < base:
            trows.append({"name": "其他", "count": base - s, "share": round(100.0 * (base - s) / base, 2)})
    put("fin_type", trows, "queryIndustryProfile --category invest")
    put("fin_region", sorted([{"name": x.get("county") or x.get("city") or x.get("province", ""),
                               "count": x.get("num", 0), "amount_wan": float(x.get("amount", 0) or 0)}
                              for x in rf.get("detail", [])], key=lambda r: -r["count"])[:10],
        "queryIndustryProfile --category invest")

    # parks
    parks_p = raw / "parks.json"
    if parks_p.exists():
        pd = json.loads(parks_p.read_text(encoding="utf-8"))
        pg = (pd.get("result") or pd).get("groups") or {}
        lst = pg.get("list") or pg.get("region") or {}
        items = lst.get("items") or lst.get("itemList") or (lst if isinstance(lst, list) else [])
        rows = []
        for i, x in enumerate(items[:10]):
            if not isinstance(x, dict):
                continue
            rows.append({"rank": i + 1,
                         "name": x.get("parkName") or x.get("name") or "",
                         "region": x.get("regionName") or x.get("cityName") or "",
                         "level": x.get("parkLevel") or x.get("level") or "",
                         "park_total": x.get("companyTotal") or x.get("parkCompanyCount") or 0,
                         "entered": x.get("companyCount") or x.get("enteredCompanyCount") or 0,
                         "ratio": round(100.0 * (x.get("companyCount") or 0) / (x.get("companyTotal") or 1), 2) if x.get("companyTotal") else 0})
        put("parks", rows, "queryParkProfile")

    for name in UNAVAILABLE:
        manifest["limitations"].append({"dataset": name, "reason": "平台聚合画像精选子集不直出该展示点（口径边界，非缺数）"})
    if not out.get("ent_trend"):
        manifest["limitations"].append({"dataset": "ent_trend", "reason": "scaleChartBundle 缺失"})

    seen = set()
    dedup = []
    for l in manifest["limitations"]:
        k = (l.get("dataset"), l.get("reason"))
        if k not in seen:
            seen.add(k)
            dedup.append(l)
    manifest["limitations"] = dedup
    for name, doc in out.items():
        (data_dir / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_dir / "data_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"datasets": sorted(out), "limitations": len(manifest["limitations"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
