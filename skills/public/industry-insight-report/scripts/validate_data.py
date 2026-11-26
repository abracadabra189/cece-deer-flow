"""S3.5 数据校验：L1 schema / L2 一致性 / L3 文稿数字回溯。退出码 0=pass 1=fail。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

P0_DATASETS = {"score", "chain", "ent_trend"}
EXEMPT_YEARS = set(range(1900, 2101))
EXEMPT_CONSTS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100, 0.0}
HEADER = ["dataset", "as_of", "source_cmd", "fetched_at", "unit", "rows"]


def _f(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _walk_numbers(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_numbers(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.add(_f(obj))


def load_data(data_dir: Path):
    data, manifest = {}, {}
    mf = data_dir / "data_manifest.json"
    if mf.exists():
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    for p in sorted(data_dir.glob("*.json")):
        if p.name == "data_manifest.json":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        data[d.get("dataset", p.stem)] = d
    return data, manifest


def l1_checks(data, failures):
    for name, d in data.items():
        for h in HEADER:
            if h not in d:
                failures.append({"level": "L1", "dataset": name, "rule": "header", "detail": f"missing {h}"})
        for r in d.get("rows", []):
            for k, v in r.items():
                if "share" in k and _f(v) is not None and not (0 <= float(v) <= 100):
                    failures.append({"level": "L1", "dataset": name, "rule": "share_range", "detail": f"{k}={v}"})
    sc = data.get("score", {}).get("rows", [{}])
    if sc and _f(sc[0].get("total")) is not None and not (0 <= float(sc[0]["total"]) <= 100):
        failures.append({"level": "L1", "dataset": "score", "rule": "total_range", "detail": str(sc[0].get("total"))})


def _total_ref(data):
    st = data.get("ent_structure", {}).get("rows", [{}])
    if st and st[0].get("total") is not None:
        return float(st[0]["total"])
    tr = data.get("ent_trend", {}).get("rows", [])
    return float(tr[-1]["stock"]) if tr else None


def l2_checks(data, failures):
    ref = _total_ref(data)
    # parts_sum
    ps = data.get("patent_summary", {}).get("rows", [{}])
    if ps and ps[0].get("parts_complete", True):
        r = ps[0]
        s = sum(float(r.get(k, 0) or 0) for k in ("fa", "fs", "sy", "wg"))
        if _f(r.get("total")) is not None and abs(s - float(r["total"])) > 0.5:
            failures.append({"level": "L2", "dataset": "patent_summary", "rule": "parts_sum", "detail": f"{s} != {r.get('total')}"})
    for ds in ("ent_capital", "ent_age"):
        rows = data.get(ds, {}).get("rows", [])
        ssum = sum(float(r.get("share", 0)) for r in rows)
        if rows and "ent_structure" in data and abs(ssum - 100) <= 0.5:
            s = sum(float(r.get("count", 0)) for r in rows)
            if abs(s - ref) > 0.5:
                failures.append({"level": "L2", "dataset": ds, "rule": "parts_sum", "detail": f"{s} != {ref}"})
    ft = data.get("fin_trend", {}).get("rows", [])
    fs_ = data.get("fin_summary", {}).get("rows", [{}])
    if ft and fs_ and fs_[0].get("amount_yi") is not None:
        s = sum(float(r.get("amount_yi", 0)) for r in ft)
        if abs(s - float(fs_[0]["amount_yi"])) > 0.5:
            failures.append({"level": "L2", "dataset": "fin_trend", "rule": "parts_sum", "detail": f"{s} != {fs_[0]['amount_yi']}"})
        c = sum(float(r.get("count", 0)) for r in ft)
        if fs_[0].get("count") is not None and abs(c - float(fs_[0]["count"])) > 0.5:
            failures.append({"level": "L2", "dataset": "fin_trend", "rule": "parts_sum", "detail": f"count {c} != {fs_[0]['count']}"})
    # shares_sum（仅对闭合分档校验；平台精选子集占比和<99.5 时跳过并在 limitations 说明）
    for name, d in data.items():
        rows = d.get("rows", [])
        if rows and all("share" in r for r in rows):
            s = sum(float(r["share"]) for r in rows)
            if s < 99.5:
                continue
            if abs(s - 100) > 0.5:
                failures.append({"level": "L2", "dataset": name, "rule": "shares_sum", "detail": f"{s:.2f}"})
    # monotonic_desc
    mono = {"ent_region": "total", "patent_tech": "count", "patent_region": "total",
            "patent_applicant": "total", "ent_top": "score", "fin_region": "count",
            "fin_inst": "count", "parks": "entered", "parks_ratio": "ratio"}
    for name, key in mono.items():
        rows = data.get(name, {}).get("rows", [])
        vals = [float(r.get(key, 0)) for r in rows if r.get(key) is not None]
        if any(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
            failures.append({"level": "L2", "dataset": name, "rule": "monotonic_desc", "detail": key})
    # subset_le
    er = data.get("ent_region", {}).get("rows", [])
    if er and ref and sum(float(r.get("total", 0)) for r in er) > ref:
        failures.append({"level": "L2", "dataset": "ent_region", "rule": "subset_le", "detail": "sum>total"})
    pr = data.get("patent_region", {}).get("rows", [])
    pt = ps[0].get("total") if ps else None
    if pr and pt and sum(float(r.get("total", 0)) for r in pr) > float(pt):
        failures.append({"level": "L2", "dataset": "patent_region", "rule": "subset_le", "detail": "sum>total"})
    # date_le_asof
    for name, d in data.items():
        for r in d.get("rows", []):
            dv = r.get("date")
            if dv and str(dv) > str(d.get("as_of", "9999")):
                failures.append({"level": "L2", "dataset": name, "rule": "date_le_asof", "detail": str(dv)})
    # unit_norm
    for name, d in data.items():
        for r in d.get("rows", []):
            if "value_yuan" in r and "display_unit" not in r:
                failures.append({"level": "L2", "dataset": name, "rule": "unit_norm", "detail": "missing display_unit"})


def derived_values(data):
    out = set()
    ref = _total_ref(data)
    for name, d in data.items():
        for r in d.get("rows", []):
            _walk_numbers(r, out)
            for k in ("count", "total", "value", "score"):
                if r.get(k) is not None and ref:
                    out.add(_f(100.0 * float(r[k]) / ref))
    tr = data.get("ent_trend", {}).get("rows", [])
    if len(tr) >= 2:
        a, b = float(tr[-2]["stock"]), float(tr[-1]["stock"])
        if a:
            out.add(_f(100.0 * (b - a) / a))
    for ds in ("fin_trend", "patent_trend"):
        rows = data.get(ds, {}).get("rows", [])
        key = "count" if ds == "fin_trend" else None
        if rows and key:
            for i in range(1, len(rows)):
                a = float(rows[i - 1][key]) or None
                if a:
                    out.add(_f(100.0 * (float(rows[i][key]) - a) / a))
    return out


def l3_check(md_text, data, failures, max_seq=0):
    allowed = derived_values(data)
    for d in data.values():
        rows = d.get("rows", [])
        _walk_numbers(rows, allowed)
        for r in rows:
            for k, v in r.items():
                if isinstance(v, str):
                    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", v):
                        try:
                            allowed.add(round(float(m.replace(",", "")), 2))
                        except ValueError:
                            pass
                if isinstance(v, (int, float)) and not isinstance(v, bool) and \
                        any(w in k for w in ("yuan", "wan", "amount")):
                    allowed.update({_f(v), _f(v / 1e4), _f(v / 1e8)})
        # 列合计（Top 合计、分布合计等文稿中常见的派生口径）
        keys = set()
        for r in rows:
            keys.update(k for k, v in r.items() if isinstance(v, (int, float)) and not isinstance(v, bool))
        for k in keys:
            allowed.add(_f(sum(float(r[k]) for r in rows if isinstance(r.get(k), (int, float)))))
    # 预清洗：标题行（章/节号）、日期（ISO 与中文）不参与回溯
    cleaned = "\n".join(l for l in md_text.splitlines() if not l.startswith("#"))
    cleaned = re.sub(r"\d{4}-\d{1,2}(?:-\d{1,2})?", " ", cleaned)
    cleaned = re.sub(r"\d{4} 年 \d{1,2} 月 \d{1,2} 日", " ", cleaned)
    tokens = re.findall(r"\d[\d,]*(?:\.\d+)?%?", cleaned)
    for t in tokens:
        pct = t.endswith("%")
        raw = t.rstrip("%").replace(",", "")
        try:
            v = round(float(raw), 2)
        except ValueError:
            continue
        if not pct and (int(v) in EXEMPT_YEARS or v in EXEMPT_CONSTS):
            continue
        if not pct and max_seq and 1 <= v <= max_seq:
            continue
        if pct:
            if v in allowed:
                continue
        elif v in allowed or _f(v) in allowed:
            continue
        failures.append({"level": "L3", "dataset": "report.md", "rule": "number_trace", "detail": t})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--md", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seq", type=int, default=0)
    a = ap.parse_args()
    data_dir, md = Path(a.data_dir), Path(a.md)
    data, _ = load_data(data_dir)
    failures = []
    l1_checks(data, failures)
    l2_checks(data, failures)
    if md.exists():
        l3_check(md.read_text(encoding="utf-8"), data, failures, a.max_seq)
    blocking = [f for f in failures if f["level"] == "L3" or
                (f["level"] in ("L1", "L2") and f["dataset"] in P0_DATASETS)]
    report = {"passed": not blocking, "checks": sorted({f["rule"] for f in failures}) or ["all"],
              "failures": failures, "p0_missing": sorted(P0_DATASETS - set(data)),
              "warnings": [{"dataset": n, "reason": "P0 数据集缺失，按数据限制降级"}
                            for n in sorted(P0_DATASETS - set(data))]}
    if not data:
        report["passed"] = False
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "failures": len(failures)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
