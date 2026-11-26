"""MCP 取数连通性自检：host 探测 → 三服务 initialize/tools → 可选解析产业并试取评分/画像。

用法：
  python scripts/check_mcp.py [--industry 摩托车] [--region 500000] [--host 127.0.0.1]
退出码：0=全通；1=有失败项（明细见输出 JSON）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mcp_client import MCPClient, MCPError  # noqa: E402  # noqa: E402

PORTS = {"NER": 18906, "enterprise": 18907, "industry": 18908}


def detect_host(explicit: str | None) -> str:
    if explicit:
        return explicit
    for h in ("127.0.0.1", "host.docker.internal"):
        try:
            socket.create_connection((h, PORTS["industry"]), timeout=2).close()
            return h
        except OSError:
            continue
    return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("MCP_HOST", ""))
    ap.add_argument("--industry", default="")
    ap.add_argument("--region", default="")
    a = ap.parse_args()
    host = detect_host(a.host or None)
    result = {"host": host, "servers": {}, "resolution": None, "probe": None}
    ok = True
    for name, port in PORTS.items():
        url = f"http://{host}:{port}/cece-mcp-servers/{name}/stream"
        try:
            with MCPClient(url) as c:
                result["servers"][name] = {"ok": True, "tools": len(c.tools())}
        except Exception as e:  # noqa: BLE001
            ok = False
            result["servers"][name] = {"ok": False, "error": str(e)[:200]}
    if a.industry:
        systems = ["SELECTED", "CSF", "NSEI", "GB", "DE"]
        for system in systems:
            try:
                with MCPClient(f"http://{host}:18906/cece-mcp-servers/NER/stream") as ner:
                    r = ner.call("search_industry_by_name", {"keyword": a.industry, "industry_type": system})
                items = r.get("匹配列表") or []
            except MCPError:
                items = []
            if items:
                items = sorted(items, key=lambda i: (int(i.get("级别") or 99), 0 if i.get("产业名称") == a.industry else 1))
                primary = items[0]
                result["resolution"] = {"system": system, "primary": primary,
                                        "matches": [{"code": i.get("产业代码"), "name": i.get("产业名称"),
                                                     "level": i.get("级别")} for i in items[:5]]}
                if a.region:
                    try:
                        with MCPClient(f"http://{host}:18908/cece-mcp-servers/industry/stream") as ind:
                            ev = ind.call("get_industry_evaluation", {
                                "industry_code": primary.get("产业代码"), "industry_type": system,
                                "region_code": a.region})
                            pt = ind.call("get_industry_company_portrait", {
                                "industry_code": primary.get("产业代码"), "industry_type": system,
                                "region_code": a.region, "scale_months": 24})
                        result["probe"] = {
                            "evaluation": {"status": ev.get("状态码"), "summary": ev.get("摘要")},
                            "portrait": {"status": pt.get("状态码"), "summary": pt.get("摘要")},
                        }
                    except MCPError as e:
                        ok = False
                        result["probe"] = {"error": str(e)[:200]}
                break
        else:
            ok = False
            result["resolution"] = {"error": f"产业「{a.industry}」在 {systems} 均未匹配"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())