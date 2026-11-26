"""S2 取数（本地 CECE MCP）：多体系解析产业 → industry/enterprise 工具取数 → raw_mcp/。

产业解析顺序：SELECTED（新华产业链）→ CSF → NSEI → GB → DE；取同层最匹配节点为主节点，
同层同关键词兄弟节点（如摩托车整车/零部件）并入企业/融资查询范围。

环境变量（可选）：MCP_HOST 指定主机（默认自动探测 127.0.0.1 / host.docker.internal）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mcp_client import MCPClient, MCPError  # noqa: E402

HOST = os.environ.get("MCP_HOST", "")
if not HOST:
    def _probe(h):
        try:
            socket.create_connection((h, 18908), timeout=2).close()
            return True
        except OSError:
            return False

    HOST = next((h for h in ("127.0.0.1", "host.docker.internal") if _probe(h)), "127.0.0.1")
URL = "http://{h}:{p}/cece-mcp-servers/{n}/stream"
NER_URL, ENT_URL, IND_URL = URL.format(h=HOST, p=18906, n="NER"), URL.format(h=HOST, p=18907, n="enterprise"), URL.format(h=HOST, p=18908, n="industry")
SYSTEMS = ["SELECTED", "CSF", "NSEI", "GB", "DE"]


def resolve_industry(keyword: str):
    """跨体系解析产业关键词，返回 (primary_item, sibling_codes)。"""
    with MCPClient(NER_URL) as ner:
        for system in SYSTEMS:
            try:
                res = ner.call("search_industry_by_name", {"keyword": keyword, "industry_type": system})
            except MCPError:
                continue
            items = res.get("匹配列表") or (res.get("数据") or {}).get("匹配列表") or []
            if not items:
                continue

            def rank(i):
                name = i.get("产业名称") or ""
                try:
                    level = int(i.get("级别") or 99)
                except ValueError:
                    level = 99
                exact = 0 if name == keyword else 1 if name.startswith(keyword) else 2
                return (level, exact)

            ordered = sorted(items, key=rank)
            primary = ordered[0]
            level, itype = rank(primary)[0], primary.get("产业类型") or system
            siblings = [i.get("产业代码") for i in ordered
                        if i.get("产业类型") == itype and rank(i)[0] == level
                        and keyword in (i.get("产业名称") or "")]
            codes = [c for c in siblings if c][:4] or [primary.get("产业代码")]
            return primary, codes, system
    return None, [], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--region-code", required=True)
    ap.add_argument("--industry-code", required=True)
    ap.add_argument("--industry-name", default="")
    ap.add_argument("--as-of", default="")
    a = ap.parse_args()
    rd = Path(a.run_dir)
    raw = rd / "raw_mcp"
    raw.mkdir(parents=True, exist_ok=True)
    meta = {"source": "mcp", "host": HOST, "fetched_at": dt.datetime.now().isoformat(),
            "region_code": a.region_code, "industry_code": a.industry_code,
            "industry_name": a.industry_name, "as_of": a.as_of, "limitations": []}

    def save(name, obj):
        (raw / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    keyword = a.industry_name or a.industry_code
    code, itype, codes = a.industry_code, "SELECTED", [a.industry_code]
    if any("\u4e00" <= ch <= "\u9fff" for ch in keyword):
        primary, sibling_codes, system = resolve_industry(keyword)
        if primary:
            code = primary.get("产业代码") or code
            itype = primary.get("产业类型") or system or itype
            codes = [c for c in sibling_codes if c] or [code]
        save("ner_resolution", {"primary": primary, "codes": codes, "system": itype})
    region = a.region_code
    meta.update({"industry_code": code, "industry_type": itype, "industry_codes": codes})

    calls = {
        "evaluation": ("get_industry_evaluation", {"industry_code": code, "industry_type": itype, "region_code": region}),
        "portrait": ("get_industry_company_portrait", {"industry_code": code, "industry_type": itype, "region_code": region, "scale_months": 24}),
        "chain": ("get_industry_chain_tree", {"root_code": code, "industry_type": itype, "region_code": region}),
        "innovation": ("get_industry_innovation", {"industry_code": code, "industry_type": itype, "region_code": region}),
        "fin_overview": ("get_industry_financing_overview", {"industry_codes": codes, "industry_type": itype, "region_code": region}),
        "fin_trend": ("get_industry_financing_trend", {"industry_codes": codes, "industry_type": itype, "region_code": region}),
        "fin_events": ("get_industry_financing_events", {"industry_codes": codes, "industry_type": itype, "region_code": region,
                                                       "financing_type": "创投融资", "page": 1, "page_size": 10}),
        "fin_investors": ("get_industry_investors", {"industry_codes": codes, "industry_type": itype, "region_code": region,
                                                    "page": 1, "page_size": 10}),
    }
    try:
        with MCPClient(IND_URL) as mc:
            for name, (tool, args) in calls.items():
                try:
                    save(name, mc.call(tool, args))
                except MCPError as e:
                    meta["limitations"].append({"dataset": name, "reason": str(e)[:200]})
    except MCPError as e:
        meta["limitations"].append({"dataset": "industry_mcp", "reason": str(e)[:200]})

    try:
        with MCPClient(ENT_URL) as ec:
            save("ent_top", ec.call("find_companies", {
                "industry_codes": codes, "industry_type": itype, "region_codes": [region],
                "sort_by": "综合评分", "sort_order": "降序", "page": 1, "page_size": 10}))
    except MCPError as e:
        meta["limitations"].append({"dataset": "ent_top", "reason": str(e)[:200]})

    (raw / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": "mcp", "industry_code": code, "industry_type": itype,
                      "industry_codes": codes, "limitations": len(meta["limitations"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())