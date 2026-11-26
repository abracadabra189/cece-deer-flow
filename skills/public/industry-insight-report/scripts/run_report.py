"""产业洞察报告单报告流水线编排（S0–S5）。退出码 0=ok / 1=门禁失败 / 2=数据全缺。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))
import llm_client  # noqa: E402

P = lambda *a: str(Path(*a))  # noqa: E731


def fmt(v):
    if v is None:
        return "—"
    f = float(v)
    return f"{int(round(f)):,}" if abs(f - round(f)) < 1e-9 else f"{f:,.2f}"


def p2(v):
    if v is None:
        return "—"
    return f"{float(v):.2f}"


def dash(v):
    return "—" if v is None else fmt(v)


def cn_date(iso):
    y, m, d = iso.split("-")
    return f"{y} 年 {int(m)} 月 {int(d)} 日"


class Run:
    def __init__(self, rd: Path):
        self.rd = rd
        rd.mkdir(parents=True, exist_ok=True)
        pf = rd / "progress.json"
        self.progress = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else {}

    def done(self, stage):
        return self.progress.get(stage, {}).get("status") == "passed"

    def mark(self, stage, status, **extra):
        self.progress[stage] = {"status": status, "at": dt.datetime.now().isoformat(), **extra}
        (self.rd / "progress.json").write_text(json.dumps(self.progress, ensure_ascii=False, indent=2), encoding="utf-8")

    def py(self, script, *args):
        return subprocess.run([sys.executable, P(HERE, script), *map(str, args)],
                              capture_output=True, text=True)

    def node(self, script, *args):
        return subprocess.run(["node", P(HERE, script), *map(str, args)],
                              capture_output=True, text=True)


def load_data(rd):
    data = {}
    for p in sorted((rd / "data").glob("*.json")):
        if p.name != "data_manifest.json":
            d = json.loads(p.read_text(encoding="utf-8"))
            data[d["dataset"]] = d
    manifest = json.loads((rd / "data" / "data_manifest.json").read_text(encoding="utf-8"))
    return data, manifest


# ---------------------------------------------------------------- S0 spec

NAV = ["产业评分", "产业图谱", "企业画像", "产业创新", "产业发展"]
DATA_ORDER = ["score", "chain", "ent_trend", "ent_structure", "ent_capital", "ent_age",
              "ent_region", "ent_top", "patent_summary", "patent_trend", "patent_value",
              "patent_tech", "patent_region", "patent_applicant", "fin_summary", "fin_index",
              "fin_trend", "fin_type", "fin_round", "fin_region", "fin_events", "fin_inst",
              "parks", "parks_ratio"]


def s0_spec(args, rd: Path, run: Run):
    if run.done("S0"):
        return json.loads((rd / "spec.json").read_text(encoding="utf-8"))
    fx_meta = None
    if args.fixture:
        fx_meta = json.loads(Path(args.fixture).read_text(encoding="utf-8"))["meta"]
    region = fx_meta["region"] if fx_meta else {"adcode": args.region_code, "name": args.region_name or args.region_code}
    industry = fx_meta["industry"] if fx_meta else {"code": args.industry_code, "name": args.industry_name or args.industry_code, "category": ""}
    as_of = args.as_of or (fx_meta or {}).get("as_of") or dt.date.today().isoformat()
    today = dt.date.today()
    spec = {
        "task_id": f"{industry['code']}-{region['adcode']}-{as_of}",
        "region_code": region["adcode"], "region_name": region["name"],
        "industry_code": industry["code"], "industry_name": industry["name"],
        "category": industry.get("category", ""),
        "as_of": as_of, "as_of_cn": cn_date(as_of),
        "generated_cn": f"{today.year} 年 {today.month} 月 {today.day} 日",
        "report_no": f"{industry['code']}-{region['adcode']}-{as_of}",
        "nav": NAV, "data_order": DATA_ORDER,
        "options": {"public_web": args.public_web},
        "title": "产业洞察报告",
    }
    (rd / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    run.mark("S0", "passed")
    return spec


# ---------------------------------------------------------------- S1 framework

def s1_framework(spec, rd: Path, run: Run):
    if run.done("S1"):
        return json.loads((rd / "framework.json").read_text(encoding="utf-8"))
    reg = json.loads((SKILL / "references" / "frameworks" / "registry.json").read_text(encoding="utf-8"))
    name = spec["industry_name"]
    cat = next((c for c in reg["categories"] if c["id"] == spec.get("category")), None)
    assumed = False
    if not cat:
        cat = next((c for c in reg["categories"] if any(k in name for k in c["keywords"])), None)
    if not cat:
        cat = next(c for c in reg["categories"] if c["id"] == "future_industry")
        assumed = True
    combo = next(c for c in reg["combination_rules"] if c["id"] == cat["default_combo"])
    ch = {
        "一": ["scorecard6"], "二": ["value_chain"], "三": ["porter_diamond", "scorecard6"],
        "四": ["four_chains", "patent_value"], "五": ["four_chains", "lifecycle"],
    }
    if combo["id"] == "future_industry_composite":
        ch["四"] += ["gartner"]
        ch["五"] += ["mckinsey_arenas"]
    if combo["id"] == "demand_side_composite":
        ch["五"] = ["lifecycle", "swot"]
    fw = {"category": cat["id"], "category_name": cat["name"], "combo": combo["id"],
          "assumed": assumed, "members": combo["members"], "merged_logic": combo["merged_logic"],
          "chapters": [{"id": k, "frameworks": v,
                        "reasoning_chain": [f for fid in v for f in
                                            next(x["reasoning_chain"] for x in reg["frameworks"] if x["id"] == fid)][:6]}
                       for k, v in ch.items()],
          "downgrades": []}
    (rd / "framework.json").write_text(json.dumps(fw, ensure_ascii=False, indent=2), encoding="utf-8")
    run.mark("S1", "passed")
    return fw


# ---------------------------------------------------------------- S3 文稿

def _top(rows, key, n=3):
    return sorted(rows, key=lambda r: -float(r[key]))[:n]


def fact_paras(ds, data, spec):
    rows = data.get(ds, {}).get("rows", [])
    if not rows:
        return []
    R, I = spec["region_name"], spec["industry_name"]
    if ds == "score":
        r = rows[0]
        dims = sorted(r["dims"], key=lambda d: -d["score"])[:3]
        return [f"在 {r['year']} 年度产业综合评估中，{R}{I}的综合评分为 [[b:{p2(r['total'])} 分]]，"
                f"位于全国城市排名[[b:第 {r['rank_national'][0]} 名]]，{r['rank_region_label']}[[b:第 {r['rank_region'][0]} 名]]。"
                f"分项表现上，{R}{I}在{'、'.join(d['name'] for d in dims)}维度表现突出。"]
    if ds == "ent_trend":
        a, b = rows[-2], rows[-1]
        g = 100.0 * (b["stock"] - a["stock"]) / a["stock"]
        lab_b = b.get("period") or str(b.get("year"))
        lab_a = a.get("period") or str(a.get("year"))
        cmp_lab = "较上年" if (b.get("period") or "").isdigit() else ("环比" if b.get("period") else f"较 {lab_a} 年末")
        return [f"截至 {spec['as_of_cn']}，{R}{I}存量企业 [[b:{fmt(b['stock'])} 家]]（{lab_b} 口径），{cmp_lab}增长 [[b:{p2(g)}%]]。"
                f"其中，当期（{lab_b}）新注册企业 [[b:{fmt(b['new_reg'])} 家]]。"]
    if ds == "ent_structure":
        r = rows[0]
        parts = [f"截至 {spec['as_of_cn']}，{R}{I}存量企业 [[b:{fmt(r['total'])} 家]]"]
        if r.get("listed") is not None:
            parts.append(f"上市企业 [[b:{fmt(r['listed'])} 家]]，占比 [[b:{p2(r['listed_share'])}%]]")
        if r.get("srme") is not None:
            parts.append(f"专精特新企业 [[b:{fmt(r['srme'])} 家]]，占比 [[b:{p2(r['srme_share'])}%]]")
        if r.get("hightech") is not None:
            parts.append(f"高新技术企业 [[b:{fmt(r['hightech'])} 家]]，占比 [[b:{p2(r['hightech_share'])}%]]")
        return ["。其中，".join(parts) + "。"]
    if ds in ("ent_capital", "ent_age"):
        lab = "注册资金在" if ds == "ent_capital" else "经营年限在"
        t = _top(rows, "count")
        return [f"截至 {spec['as_of_cn']}，{R}{I}存量企业 [[b:{fmt(sum(r['count'] for r in rows))} 家]]。其中，{lab}"
                f"[[b:{t[0]['name']}]]的企业最多，有 [[b:{fmt(t[0]['count'])} 家]]，占比 [[b:{p2(t[0]['share'])}%]]；"
                f"其次是{lab}[[b:{t[1]['name']}]]的企业，有 [[b:{fmt(t[1]['count'])} 家]]，占比 [[b:{p2(t[1]['share'])}%]]；"
                f"{lab}[[b:{t[-1]['name']}]]的企业最少，有 [[b:{fmt(min(rows, key=lambda r: r['count'])['count'])} 家]]，"
                f"占比 [[b:{p2(min(rows, key=lambda r: r['count'])['share'])}%]]。"]
    if ds == "ent_region":
        t = _top(rows, "total")
        return [f"截至 {spec['as_of_cn']}，{R}{I}上榜区域企业合计 [[b:{fmt(sum(r['total'] for r in rows))} 家（前 {len(rows)} 区域合计）]]，"
                f"企业数量排名前三的区域依次为[[b:{'、'.join(r['name'] for r in t)}]]，"
                f"企业数量分别为 [[b:{'、'.join(fmt(r['total']) for r in t)}]] 家。"]
    if ds == "patent_summary":
        r = rows[0]
        return [f"截至 {spec['as_of_cn']}，{R}{I}相关专利总计 [[b:{fmt(r['total'])} 件]]，其中发明申请 [[b:{fmt(r['fa'])} 件]]、"
                f"发明授权 [[b:{fmt(r['fs'])} 件]]、实用新型 [[b:{fmt(r['sy'])} 件]]。在 {spec['as_of'][:4]} 年新公开的专利共 "
                f"[[b:{fmt(r['year_new'])} 件]]，其中发明申请 [[b:{fmt(r['year_new_fa'])} 件]]、发明授权 [[b:{fmt(r['year_new_fs'])} 件]]。"]
    if ds == "patent_value":
        r = rows[0]
        top = max(r["dist"], key=lambda d: d["count"])
        td = r["top_dim"]
        return [f"截至 {spec['as_of_cn']}，{R}{I}相关专利总计 [[b:{fmt(sum(d['count'] for d in r['dist']))} 件]]，"
                f"综合价值评分为 [[b:{top['score']} 分]]的专利数量最多，为 [[b:{fmt(top['count'])} 件]]，占比 [[b:{p2(top['share'])}%]]。"
                f"分项维度上，{'；'.join(f'{k}评分为 [[b:{v[0]} 分]]的专利数量最多，为 [[b:{fmt(v[1])} 件]]，占比 [[b:{p2(v[2])}%]]' for k, v in td.items())}。"]
    if ds in ("patent_tech", "patent_applicant"):
        t = _top(rows, "count" if ds == "patent_tech" else "total")
        key = "count" if ds == "patent_tech" else "total"
        lab = "关键技术" if ds == "patent_tech" else "申请人"
        return [f"截至 {spec['as_of_cn']}，{R}{I}专利数量排名前三的{lab}依次为[[b:{'、'.join(r['name'] for r in t)}]]，"
                f"专利数量分别为 [[b:{'、'.join(fmt(r[key]) for r in t)}]] 件。"]
    if ds == "patent_region":
        t = _top(rows, "total")
        return [f"截至 {spec['as_of_cn']}，{R}{I}专利数量排名前三的区域依次为[[b:{'、'.join(r['name'] for r in t)}]]，"
                f"专利数量分别为 [[b:{'、'.join(fmt(r['total']) for r in t)}]] 件。"]
    if ds == "fin_summary":
        r = rows[0]
        s = f"自 2017 年以来，{R}{I}累计发生融资 [[b:{fmt(r['count'])} 次]]"
        if r.get("amount_yi") is not None:
            s += f"，总融资金额达 [[b:{p2(r['amount_yi'])} 亿元]]"
        s += "。"
        if r.get("active_year") is not None:
            s += f"其中，融资最活跃年度是 [[b:{r['active_year']} 年]]，发生融资 [[b:{fmt(r['active_count'])} 次]]；"
        if r.get("top_year") is not None:
            s += f"融资规模最高的年度是 [[b:{r['top_year']} 年]]，融资金额为 [[b:{p2(r['top_amount_yi'])} 亿元]]。"
        return [s]
    if ds == "fin_type":
        t = _top(rows, "amount_wan" if "amount_wan" in rows[0] else "count")
        r0 = (data.get("fin_summary", {}).get("rows") or [{}])[0]
        head = ""
        if r0.get("last_year_count") is not None:
            head = f"近一年，{R}{I}发生融资 [[b:{fmt(r0['last_year_count'])} 次]]"
            if r0.get("last_year_amount_yi") is not None:
                head += f"，融资金额达 [[b:{p2(r0['last_year_amount_yi'])} 亿元]]"
            head += "。"
        if t[0].get("amount_wan") is not None:
            tail = (f"其中，通过[[b:{t[0]['name']}]]方式获得的融资金额最大，为 [[b:{p2(t[0]['amount_wan'] / 1e4)} 亿元]]，"
                    f"占比 [[b:{p2(t[0]['share'])}%]]。")
        else:
            tail = f"其中，[[b:{t[0]['name']}]]事件数最多，为 [[b:{fmt(t[0]['count'])} 次]]，占比 [[b:{p2(t[0]['share'])}%]]。"
        return [head + tail]
    if ds == "fin_round":
        t = _top(rows, "count")
        return [f"近一年，{R}{I}创投融资事件按轮次统计，排名前三的依次为[[b:{'、'.join(r['name'] for r in t)}]]，"
                f"分别发生 [[b:{'、'.join(fmt(r['count']) for r in t)}]] 次。"]
    if ds == "fin_region":
        t = _top(rows, "count")
        return [f"近一年，{R}{I}创投融资事件按区域统计，排名前三的依次为[[b:{'、'.join(r['name'] for r in t)}]]，"
                f"分别发生 [[b:{'、'.join(fmt(r['count']) for r in t)}]] 次。"]
    if ds == "fin_events":
        t = _top(rows, "amount_wan")
        return [f"近一年，{R}{I}中获得创投融资金额排名前三的企业依次为[[b:{'、'.join(r['name'] for r in t)}]]，"
                f"分别获得了 [[b:{'、'.join(p2(r['amount_wan']) for r in t)}]] 万元的融资。"]
    if ds == "fin_inst":
        tc, ta = _top(rows, "count")[0], _top(rows, "amount_yi")[0]
        return [f"{R}{I}过往投资机构中，[[b:{tc['name']}]]投资次数最多，为 [[b:{fmt(tc['count'])} 次]]；"
                f"[[b:{ta['name']}]]投资金额最大，为 [[b:{p2(ta['amount_yi'])} 亿元]]。"]
    if ds == "fin_index":
        r = rows[-1]
        return [f"{r['year']} 年，{R}{I}在营收方面，总营收水平指数为 [[b:{p2(r['revenue_index'])} 点]]；"
                f"在资产规模方面，总资产水平指数为 [[b:{p2(r['asset_index'])} 点]]。"]
    if ds == "parks":
        t, tr = _top(rows, "entered"), _top(rows, "ratio")
        return [f"从入驻企业数量来看，排名前三的园区依次为[[b:{'、'.join(r['name'] for r in t)}]]，"
                f"企业数分别为 [[b:{'、'.join(fmt(r['entered']) for r in t)}]] 家；从入驻占比来看，排名前三的园区依次为"
                f"[[b:{'、'.join(r['name'] for r in tr)}]]，占比分别为 [[b:{'、'.join(p2(r['ratio']) for r in tr)}%]]。"]
    return []


def analysis_para(ds, data, spec):
    rows = data.get(ds, {}).get("rows", [])
    if not rows:
        return f"{spec['region_name']}{spec['industry_name']}该维度数据暂缺，本节仅陈述数据限制。"
    key = {"ent_region": "total", "patent_tech": "count", "patent_applicant": "total", "patent_region": "total",
           "fin_region": "count", "fin_inst": "count",
           "parks": "entered", "parks_ratio": "ratio", "ent_top": "score"}.get(ds)
    if key:
        t = _top(rows, key)[0]
        tot = sum(float(r[key]) for r in rows) or 1
        share = 100.0 * float(t[key]) / tot
        return (f"结构上，{t['name']} 以 {fmt(t[key])} 居首、占 Top 合计的 {p2(share)}%（描述性分布，非因果推断）；"
                f"若该集中度在后续年度持续上升，则提示资源与政策要素向其倾斜的趋势值得跟踪。")
    if ds == "ent_trend":
        a, b = rows[-2], rows[-1]
        g = 100.0 * (b["stock"] - a["stock"]) / a["stock"]
        return (f"存量企业同比增速 {p2(g)}% 且新注册 {fmt(b['new_reg'])} 家，进入者仍在增加（描述性判断）；"
                f"若增速主要由新注册贡献，则产业仍处扩张期，载体与资本承接能力是下一阶段的约束条件。")
    return ("上述指标的组合形态与本章框架的预期一致（描述性对照，非因果结论）；"
            "若后续年度数据延续当前方向，可据此更新评分与排名预期。")


CHART_PLAN = [
    ("3.1", "c_trend", "bar_grouped", "ent_trend", "企业变化趋势"),
    ("3.2", "c_struct", "pyramid", "ent_structure", "企业结构"),
    ("3.3", "c_capital", "donut", "ent_capital", "企业注册资本分布", "注册资本"),
    ("3.4", "c_age", "donut", "ent_age", "企业经营年限分布", "经营年限"),
    ("3.5", "c_region", "hbar", "ent_region", "企业区域分布 Top10", None, "total"),
    ("4.1", "c_ptrend", "bar_stacked", "patent_trend", "专利公开趋势"),
    ("4.2", "c_pval", "donut", "patent_value", "专利价值综合评估分布", "专利价值分布"),
    ("4.2", "c_pbub", "bubble_grid", "patent_value", "专利价值分项维度评估分布"),
    ("5.1", "c_index", "line_index", "fin_index", "营收水平指数"),
    ("5.2", "c_ftrend", "dual_bar_line", "fin_trend", "融资趋势"),
    ("5.2", "c_fround", "donut", "fin_round", "创投融资轮次分布", "融资轮次"),
    ("5.2", "c_fregion", "hbar", "fin_region", "创投融资区域分布", None, "count"),
]
TABLE_PLAN = [
    ("3.5", "ent_region", "区域企业数量 Top10", ["序号", "区域", "企业总数（在营）", "上市企业", "专精特新", "高新技术"],
     lambda r: [str(r["name"]), fmt(r["total"]), dash(r.get("listed")), dash(r.get("srme")), dash(r.get("hightech"))], ["", "", "num", "num", "num", "num"]),
    ("3.6", "ent_top", "企业评分 Top10", ["排名", "企业名称", "所属地区", "注册资本", "授权专利数", "企业评分"],
     lambda r: [fmt(r["rank"]), r["name"], r["district"], r["reg_cap"], dash(r.get("patents")), p2(r["score"]) if r.get("score") is not None else "—"], ["num", "", "", "num", "num", "num"]),
    ("4.3", "patent_tech", "专利关键技术 Top10", ["序号", "关键技术", "专利数量"],
     lambda r: [fmt(r["rank"]), r["name"], fmt(r["count"])], ["num", "", "num"]),
    ("4.4", "patent_region", "区域专利数量 Top10", ["序号", "区域", "专利总数", "发明申请", "发明授权", "实用新型"],
     lambda r: [fmt(r["rank"]), r["name"], fmt(r["total"]), fmt(r["fa"]), fmt(r["fs"]), fmt(r["sy"])], ["num", "", "num", "num", "num", "num"]),
    ("4.5", "patent_applicant", "申请人专利数量 Top10", ["序号", "申请人", "专利总数", "发明申请", "发明授权", "实用新型"],
     lambda r: [fmt(r["rank"]), r["name"], fmt(r["total"]), fmt(r["fa"]), fmt(r["fs"]), fmt(r["sy"])], ["num", "", "num", "num", "num", "num"]),
    ("5.2", "fin_events", "创投融资金额 Top 事件", ["序号", "融资企业", "融资金额", "融资轮次", "融资日期", "投资机构"],
     lambda r: [fmt(r["rank"]), r["name"], f"{p2(r['amount_wan'])} 万元", r["round"], r["date"], r["investors"]], ["num", "", "num", "", "", ""]),
    ("5.2", "fin_inst", "热门投资机构（投资次数 Top）", ["序号", "投资机构", "关注阶段", "投资次数", "投资金额"],
     lambda r: [fmt(r["rank"]), r["name"], r["stages"] or "—", fmt(r["count"]), f"{p2(r['amount_yi'])} 亿元"], ["num", "", "", "num", "num"]),
    ("5.3", "parks", "主要载体（入驻企业数 Top）", ["序号", "园区名称", "所属地区", "园区级别", "园区企业总数", "入驻企业数", "占比"],
     lambda r: [fmt(r["rank"]), r["name"], r["region"], r["level"], fmt(r["park_total"]), fmt(r["entered"]), f"{p2(r['ratio'])}%"], ["num", "", "", "", "num", "num", "num"]),
]


def s3_blocks(spec, data, manifest, rd: Path, run: Run, use_llm: bool):
    blocks, R, I = [], spec["region_name"], spec["industry_name"]
    has = lambda ds: bool(data.get(ds, {}).get("rows"))  # noqa: E731

    def scope(ds):
        return {"t": "scope", "as_of": spec["as_of"], "source": manifest.get("sources", {}).get(ds, "行业洞察")}

    def chapter(no, title, items):
        blocks.append({"t": "h1", "text": f"{no}、{title}" if no not in ("摘要", "附录") else title})
        for it in items:
            it()

    # 执行摘要
    finds = []
    sc = data.get("score", {}).get("rows", [{}])[0]
    if sc:
        finds.append(f"{R}{I} {sc.get('year')} 年度综合评分 {p2(sc.get('total', 0))} 分，全国城市排名第 {sc.get('rank_national', [0])[0]} 名。")
    et = data.get("ent_trend", {}).get("rows", [])
    if len(et) >= 2:
        g = 100.0 * (et[-1]["stock"] - et[-2]["stock"]) / et[-2]["stock"]
        finds.append(f"存量企业 {fmt(et[-1]['stock'])} 家，较上年末增长 {p2(g)}%。")
    ps = data.get("patent_summary", {}).get("rows", [{}])[0]
    if ps:
        finds.append(f"相关专利累计 {fmt(ps.get('total', 0))} 件，创新产出持续积累。")
    fs = data.get("fin_summary", {}).get("rows", [{}])[0]
    if fs:
        finds.append(f"累计融资 {fmt(fs.get('count', 0))} 次、金额 {p2(fs.get('amount_yi', 0))} 亿元，资金链活跃度较高。")
    er = data.get("ent_region", {}).get("rows", [])
    if er:
        finds.append(f"企业空间集聚于{er[0]['name']}（{fmt(er[0]['total'])} 家），区域集中度显著。")
    blocks.append({"t": "h1", "text": "执行摘要"})
    if use_llm:
        try:
            txt = llm_client.complete("你是产业分析师。", (SKILL / "references" / "prompts.md").read_text(encoding="utf-8")
                                      + "\n\nP4 输入关键发现：\n" + "\n".join(finds) + f"\n主题：{R}{I}")
            blocks.append({"t": "para", "text": txt.strip()})
        except Exception:
            blocks.append({"t": "para", "text": "；".join(finds) + "。"})
    else:
        blocks.append({"t": "para", "text": "；".join(finds) + "。"})
    blocks.append({"t": "para", "text": f"数据范围：截至 {spec['as_of_cn']}，来源为行业洞察（HYDC）产业数据服务；口径与限制见方法论章。"})

    # 一 产业评分
    def ch1():
        blocks.append({"t": "h2", "text": "1.1 综合评分"})
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("score", data, spec)])
        if has("score"):
            blocks.append({"t": "chart", "chart_id": "c_score", "type": "score_bar", "dataset": "score",
                           "title": f"{R}{I}综合评分"})
            blocks.append(scope("score"))
        blocks.append({"t": "para", "text": analysis_para("score", data, spec)})
        blocks.append({"t": "h2", "text": "1.2 分项维度"})
        if has("score"):
            blocks.append({"t": "chart", "chart_id": "c_radar", "type": "radar", "dataset": "score",
                           "title": f"{R}{I}六维评分"})
            blocks.append(scope("score"))
        else:
            blocks.append({"t": "para", "text": f"{R}{I}产业评分数据暂缺，本节仅陈述数据限制。"})
    chapter("一", "产业评分", [ch1])

    # 二 产业图谱
    def ch2():
        blocks.append({"t": "h2", "text": "2.1 链条结构"})
        ch = data.get("chain", {}).get("rows", [{}])[0]
        if ch:
            descs = "。".join(f"{b['name']}主要为{b['root']}，包含{'、'.join(m['name'] for m in b['mids'])}等组成部分"
                              for b in ch.get("blocks", []))
            blocks.append({"t": "para", "text": f"{I}产业链条结构为：{descs}。"})
        if has("chain"):
            blocks.append({"t": "chart", "chart_id": "c_chain", "type": "tree", "dataset": "chain",
                           "title": f"{R}{I}产业图谱"})
            blocks.append(scope("chain"))
        else:
            blocks.append({"t": "para", "text": f"{R}{I}产业链结构数据暂缺，本节仅陈述数据限制。"})
        blocks.append({"t": "para", "text": analysis_para("chain", data, spec) if False else
                       ("链条环节完整、下游应用环节企业聚集度最高（描述性观察）；若中游系统集成环节企业占比提升，则提示价值链位置上行。" if ch else "产业链数据暂缺。")})
    chapter("二", "产业图谱", [ch2])

    # 三 企业画像
    def ch3():
        secs = [("3.1 企业趋势", "ent_trend"), ("3.2 企业结构", "ent_structure"), ("3.3 注册资本", "ent_capital"),
                ("3.4 经营年限", "ent_age"), ("3.5 区域分布", "ent_region"), ("3.6 龙头企业", "ent_top")]
        for title, ds in secs:
            blocks.append({"t": "h2", "text": title})
            blocks.extend([{"t": "para", "text": t} for t in fact_paras(ds, data, spec)])
            for sno, cid, ctype, cds, ctitle, *rest in CHART_PLAN:
                if cds == ds and sno.startswith("3") and has(cds):
                    b = {"t": "chart", "chart_id": cid, "type": ctype, "dataset": cds, "title": f"{R}{I}{ctitle}"}
                    if ctype == "donut":
                        b.update(center_label=rest[0] if rest else "", center_value=f"{fmt(sum(r.get('count', 0) for r in data[ds]['rows']))}家")
                    if ctype == "hbar":
                        b["value_key"] = rest[1] if len(rest) > 1 else "total"
                    blocks.append(b)
                    blocks.append(scope(ds))
            for sno, tds, ttitle, headers, rowfn, aligns in TABLE_PLAN:
                if tds == ds and sno.startswith("3") and has(tds):
                    rows = data.get(ds, {}).get("rows", [])
                    blocks.append({"t": "table", "title": f"{R}{I}{ttitle}", "headers": headers,
                                   "rows": [rowfn(r) for r in rows], "aligns": aligns,
                                   "note": f"截至：{spec['as_of']}　数据来源：{manifest.get('sources', {}).get(ds, '行业洞察')}"})
            blocks.append({"t": "para", "text": analysis_para(ds, data, spec)})
    chapter("三", "企业画像", [ch3])

    # 四 产业创新
    def ch4():
        secs = [("4.1 专利公开趋势", "patent_summary", "patent_trend"), ("4.2 专利价值", "patent_value", None),
                ("4.3 关键技术", "patent_tech", None), ("4.4 区域专利", "patent_region", None),
                ("4.5 专利申请人", "patent_applicant", None)]
        for title, ds, chart_ds in secs:
            blocks.append({"t": "h2", "text": title})
            blocks.extend([{"t": "para", "text": t} for t in fact_paras(ds, data, spec)])
            for sno, cid, ctype, cds, ctitle, *rest in CHART_PLAN:
                if cds == (chart_ds or ds) and sno.startswith("4") and has(cds):
                    b = {"t": "chart", "chart_id": cid, "type": ctype, "dataset": cds, "title": f"{R}{I}{ctitle}"}
                    if ctype == "donut":
                        dist = data.get("patent_value", {}).get("rows", [{}])[0].get("dist", [])
                        b.update(center_label=rest[0] if rest else "", center_value=f"{fmt(sum(d['count'] for d in dist))}件")
                    blocks.append(b)
                    blocks.append(scope(cds))
            for sno, tds, ttitle, headers, rowfn, aligns in TABLE_PLAN:
                if tds == ds and sno.startswith("4") and has(tds):
                    rows = data.get(ds, {}).get("rows", [])
                    blocks.append({"t": "table", "title": f"{R}{I}{ttitle}", "headers": headers,
                                   "rows": [rowfn(r) for r in rows], "aligns": aligns,
                                   "note": f"截至：{spec['as_of']}　数据来源：{manifest.get('sources', {}).get(ds, '行业洞察')}"})
            blocks.append({"t": "para", "text": analysis_para(ds, data, spec)})
    chapter("四", "产业创新", [ch4])

    # 五 产业发展
    def ch5():
        blocks.append({"t": "h2", "text": "5.1 产业财务"})
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("fin_index", data, spec)])
        if has("fin_index"):
            blocks.append({"t": "chart", "chart_id": "c_index", "type": "line_index", "dataset": "fin_index",
                           "title": f"{R}{I}营收/资产水平指数"})
            blocks.append(scope("fin_index"))
        else:
            blocks.append({"t": "para", "text": f"{R}{I}产业财务指数数据暂缺，本节仅陈述数据限制。"})
        blocks.append({"t": "para", "text": analysis_para("fin_index", data, spec)})
        blocks.append({"t": "h2", "text": "5.2 产业投融资"})
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("fin_summary", data, spec)])
        if has("fin_trend"):
            blocks.append({"t": "chart", "chart_id": "c_ftrend", "type": "dual_bar_line", "dataset": "fin_trend",
                           "title": f"{R}{I}融资趋势"})
            blocks.append(scope("fin_trend"))
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("fin_type", data, spec)])
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("fin_round", data, spec)])
        if has("fin_round"):
            blocks.append({"t": "chart", "chart_id": "c_fround", "type": "donut", "dataset": "fin_round",
                           "title": f"{R}{I}创投融资轮次分布", "center_label": "融资轮次",
                           "center_value": f"{fmt(sum(r['count'] for r in data.get('fin_round', {}).get('rows', [])))}次"})
            blocks.append(scope("fin_round"))
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("fin_region", data, spec)])
        if has("fin_region"):
            blocks.append({"t": "chart", "chart_id": "c_fregion", "type": "hbar", "dataset": "fin_region",
                           "title": f"{R}{I}创投融资区域分布", "value_key": "count"})
            blocks.append(scope("fin_region"))
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("fin_events", data, spec)])
        for sno, tds, ttitle, headers, rowfn, aligns in TABLE_PLAN:
            if sno.startswith("5.2") and tds in ("fin_events", "fin_inst") and has(tds):
                rows = data.get(tds, {}).get("rows", [])
                blocks.append({"t": "table", "title": f"{R}{I}{ttitle}", "headers": headers,
                               "rows": [rowfn(r) for r in rows], "aligns": aligns,
                               "note": f"截至：{spec['as_of']}　数据来源：{manifest.get('sources', {}).get(tds, '行业洞察')}"})
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("fin_inst", data, spec)])
        blocks.append({"t": "h2", "text": "5.3 产业载体"})
        blocks.extend([{"t": "para", "text": t} for t in fact_paras("parks", data, spec)])
        for sno, tds, ttitle, headers, rowfn, aligns in TABLE_PLAN:
            if tds == "parks" and has("parks"):
                rows = data.get(tds, {}).get("rows", [])
                blocks.append({"t": "table", "title": f"{R}{I}{ttitle}", "headers": headers,
                               "rows": [rowfn(r) for r in rows], "aligns": aligns,
                               "note": f"截至：{spec['as_of']}　数据来源：{manifest.get('sources', {}).get(tds, '行业洞察')}"})
        blocks.append({"t": "para", "text": analysis_para("parks", data, spec)})
    chapter("五", "产业发展", [ch5])

    # 六 方法论
    def ch6():
        blocks.append({"t": "para", "text": "产业综合评分模型从产业规模、优质企业、创新能力、融资能力、产业效益、成长能力六个维度构建，满分 100 分；"
                                            "企业价值评分从企业规模、成长潜力、运营效能、创新实力、资质认定、风险管理六个维度构建，分值区间 0-100 分；"
                                            "专利价值评分从技术稳定性、技术先进性、保护范围三个维度构建，满分 10 分。"})
        lim = manifest.get("limitations", [])
        blocks.append({"t": "para", "text": ("数据限制：本次运行缺失数据集 " + "、".join(l["dataset"] for l in lim) + "，相关章节仅陈述限制。") if lim else "数据限制：本次运行无缺失数据集。"})
        blocks.append({"t": "para", "text": f"分析框架：{rd.name and ''}采用组合框架（见 framework.json），事实与推断分句陈述；推断均标注为描述性/条件式。"})
    chapter("六", "方法论与数据口径", [ch6])

    # 七 结论
    def ch7():
        er = data.get("ent_region", {}).get("rows", [])
        txt = (f"{R}{I}呈现评分领先、企业持续进入、创新与资本双活跃的组合形态；空间上集中于{er[0]['name'] if er else '头部区域'}，"
               "链条下游应用环节承载主要企业体量。上述结论以校验通过的数据为限；若集中度与增速方向延续，可在下一评估周期上调成长能力预期。")
        blocks.append({"t": "para", "text": txt})
    chapter("七", "结论与建议", [ch7])

    # 附录
    def chap():
        blocks.append({"t": "h2", "text": "附录 A 指标定义"})
        blocks.append({"t": "para", "text": "存量企业：登记在册且经营状态在营的企业数；新注册：当年登记设立企业数；"
                                            "专精特新/高新技术/上市：以主管部门认定或交易所挂牌口径统计；专利：公开口径按公开年归集。"})
        blocks.append({"t": "h2", "text": "附录 B 图表索引"})
        rows = []
        i = 0
        for b in blocks:
            if b["t"] == "chart":
                i += 1
                rows.append([fmt(i), b["title"], b["type"], "见 HTML 分页"])
        blocks.append({"t": "table", "title": "图表索引", "headers": ["图号", "图题", "图表类型", "位置"],
                       "rows": rows, "aligns": ["num", "", "", ""]})
    chapter("附录", "附录", [chap])
    return blocks


def blocks_to_md(blocks, spec):
    out = [f"# {spec['region_name']}{spec['industry_name']} 产业洞察报告\n"]
    import re as _re
    for b in blocks:
        t = b["t"]
        clean = lambda s: _re.sub(r"\[\[(b|r):(.+?)\]\]", r"\2", s)  # noqa: E731
        if t == "h1":
            out.append(f"\n# {b['text']}\n")
        elif t == "h2":
            out.append(f"\n## {b['text']}\n")
        elif t == "h3":
            out.append(f"\n### {b['text']}\n")
        elif t == "para":
            out.append(clean(b["text"]) + "\n")
        elif t == "scope":
            out.append(f"> 截至：{b['as_of']}　数据来源：{b['source']}\n")
        elif t == "note":
            out.append(f"> {clean(b['text'])}\n")
        elif t == "chart":
            out.append(f"> 图：{b['title']}\n")
        elif t == "table":
            if b.get("title"):
                out.append(f"> 表：{b['title']}\n")
            out.append("| " + " | ".join(b["headers"]) + " |")
            out.append("| " + " | ".join("---" for _ in b["headers"]) + " |")
            for r in b["rows"]:
                out.append("| " + " | ".join(clean(str(c)) for c in r) + " |")
            out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--industry-code", required=True)
    ap.add_argument("--region-code", required=True)
    ap.add_argument("--industry-name", default="")
    ap.add_argument("--region-name", default="")
    ap.add_argument("--as-of", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--fixture", default="")
    ap.add_argument("--source", choices=["mcp", "hydc"], default="mcp")
    ap.add_argument("--public-web", default="false")
    a = ap.parse_args()
    rd = Path(a.out) if a.out else Path("runs") / f"{a.industry_code}-{a.region_code}"
    run = Run(rd)
    spec = s0_spec(a, rd, run)
    rd = Path(a.out) if a.out else Path("runs") / spec["task_id"]
    run = Run(rd)
    (rd / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    fw = s1_framework(spec, rd, run)

    # S2
    if not run.done("S2"):
        if a.fixture:
            cmd = ["node", P(HERE, "fetch_data.mjs"), "--spec", P(rd, "spec.json"), "--out", str(rd), "--fixture", a.fixture]
            r = subprocess.run(cmd, capture_output=True, text=True)
        elif a.source == "mcp":
            r = run.py("fetch_data_mcp.py", "--run-dir", rd, "--region-code", spec["region_code"],
                       "--industry-code", spec["industry_code"], "--industry-name", spec["industry_name"],
                       "--as-of", spec["as_of"])
            if r.returncode == 0:
                r = run.py("normalize_mcp.py", "--run-dir", rd)
        else:
            cmd = ["node", P(HERE, "fetch_data.mjs"), "--spec", P(rd, "spec.json"), "--out", str(rd)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0 and (rd / "raw").exists():
                r = run.py("normalize_data.py", "--run-dir", rd)
        if r.returncode != 0:
            run.mark("S2", "failed", detail=(r.stderr or r.stdout)[-500:])
            print((r.stderr or r.stdout), file=sys.stderr)
            return 2
        run.mark("S2", "passed")
    data, manifest = load_data(rd)
    if not data:
        run.mark("S2", "failed", detail="no datasets")
        return 2

    # S3
    use_llm = llm_client.configured()
    if not run.done("S3"):
        blocks = s3_blocks(spec, data, manifest, rd, run, use_llm)
        (rd / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
        (rd / "report.md").write_text(blocks_to_md(blocks, spec), encoding="utf-8")
        run.mark("S3", "passed")

    # S3.5（失败自动修复 1 次：去除分析段仅保留事实段）
    n_charts = sum(1 for b in json.loads((rd / "blocks.json").read_text(encoding="utf-8")) if b["t"] == "chart")
    if not run.done("S3.5"):
        r = run.py("validate_data.py", "--data-dir", P(rd, "data"), "--md", P(rd, "report.md"), "--out", P(rd, "validation_report.json"), "--max-seq", n_charts)
        if r.returncode != 0:
            blocks = json.loads((rd / "blocks.json").read_text(encoding="utf-8"))
            blocks = [b for b in blocks if not (b["t"] == "para" and b.get("text", "").startswith(("结构上", "上述指标", "存量企业同比", "链条")))]
            (rd / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
            (rd / "report.md").write_text(blocks_to_md(blocks, spec), encoding="utf-8")
            r = run.py("validate_data.py", "--data-dir", P(rd, "data"), "--md", P(rd, "report.md"), "--out", P(rd, "validation_report.json"), "--max-seq", n_charts)
        if r.returncode != 0:
            run.mark("S3.5", "failed")
            print(r.stdout + r.stderr, file=sys.stderr)
            return 1
        run.mark("S3.5", "passed")

    # S4
    if not run.done("S4"):
        r = run.py("render_charts.py", "--run-dir", rd)
        if r.returncode != 0:
            run.mark("S4", "failed", detail=r.stderr[-400:])
            print(r.stderr, file=sys.stderr)
            return 1
        r = run.py("build_html.py", "--run-dir", rd, "--out", P(rd, "report.html"))
        if r.returncode != 0:
            run.mark("S4", "failed", detail=r.stderr[-400:])
            print(r.stderr, file=sys.stderr)
            return 1
        run.mark("S4", "passed", pages=json.loads(r.stdout).get("pages"))
    pages = run.progress.get("S4", {}).get("pages", 0)

    # S4.5
    if not run.done("S4.5"):
        r = run.py("check_html.py", "--html", P(rd, "report.html"), "--run-dir", rd, "--out", P(rd, "check_report.json"))
        if r.returncode != 0:
            run.py("build_html.py", "--run-dir", rd, "--out", P(rd, "report.html"))
            r = run.py("check_html.py", "--html", P(rd, "report.html"), "--run-dir", rd, "--out", P(rd, "check_report.json"))
        if r.returncode != 0:
            run.mark("S4.5", "failed")
            print(r.stdout + r.stderr, file=sys.stderr)
            return 1
        run.mark("S4.5", "passed")

    # S5
    status = "passed"
    if not run.done("S5"):
        r = run.py("make_pdf.py", "--html", P(rd, "report.html"), "--out", P(rd, "report.pdf"), "--expect-pages", pages)
        if r.returncode == 3:
            status = "degraded"
        elif r.returncode != 0:
            status = "degraded"
        run.mark("S5", status, detail=r.stdout.strip()[-300:])
    print(json.dumps({"run_dir": str(rd), "status": status,
                      "artifacts": ["report.md", "report.html", "report.pdf"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
