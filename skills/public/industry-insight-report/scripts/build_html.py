"""S4b 分页 HTML 组装：封面/页眉页脚/装箱分页/表格跨页。单文件自包含。"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

CONTENT_H = 243.0  # mm
CONTENT_W = 178.0


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(text):
    t = esc(text)
    t = re.sub(r"\[\[b:(.+?)\]\]", r'<span class="em-b">\1</span>', t)
    t = re.sub(r"\[\[r:(.+?)\]\]", r'<span class="em-r">\1</span>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t


def est_h(b, charts):
    t = b["t"]
    if t == "h1":
        return 16
    if t == "h2":
        return 12
    if t == "h3":
        return 10
    if t == "scope":
        return 6
    if t == "note":
        return 7
    if t == "para":
        return math.ceil(len(b["text"]) / 47) * 6.7 + 3
    if t == "chart":
        return charts.get(b["chart_id"], {}).get("h_mm", 90) + 16
    if t == "table":
        h = 9
        for row in b["rows"]:
            lines = max(1, min(6, max(math.ceil(len(str(c)) / 14) for c in row)))
            h += 8 * lines
        return h + 6
    return 8


def split_table(b, avail):
    """返回 (fit_block_or_None, rest_block_or_None)"""
    head_h, row_hs = 9, []
    for row in b["rows"]:
        lines = max(1, min(6, max(math.ceil(len(str(c)) / 14) for c in row)))
        row_hs.append(8 * lines)
    total = head_h + sum(row_hs) + 6
    if total <= avail:
        return b, None
    fit_rows, used, i = [], head_h, 0
    while i < len(b["rows"]) and used + row_hs[i] <= avail - 6 and len(fit_rows) >= 0:
        fit_rows.append(b["rows"][i])
        used += row_hs[i]
        i += 1
        if avail - used < 21:  # 至少留 3 行给下一页
            break
    if not fit_rows:
        return None, b
    rest = dict(b, rows=b["rows"][len(fit_rows):]) if len(fit_rows) < len(b["rows"]) else None
    return dict(b, rows=fit_rows, continued=True), rest


def pack(blocks, charts):
    pages, cur, used = [], [], 0.0
    i = 0
    while i < len(blocks):
        b = blocks[i]
        h = est_h(b, charts)
        stick = b["t"] in ("h2", "h3") and i + 1 < len(blocks)
        need = h + (est_h(blocks[i + 1], charts) if stick else 0)
        if b["t"] == "table":
            fit, rest = split_table(b, CONTENT_H - used)
            if fit is None:
                pages.append(cur)
                cur, used = [], 0.0
                continue
            cur.append(fit)
            used += est_h(fit, charts)
            if rest:
                blocks.insert(i + 1, rest)
            i += 1
            continue
        if used + need > CONTENT_H:
            pages.append(cur)
            cur, used = [], 0.0
            continue
        cur.append(b)
        used += h
        i += 1
    if cur:
        pages.append(cur)
    return pages


CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: 'Source Han Sans SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif; color: #333; }
.page { width: 210mm; height: 297mm; position: relative; overflow: hidden; background: #F7F9FB; page-break-after: always; }
.content { position: absolute; left: 16mm; right: 16mm; top: 30mm; height: 243mm; }
.header { position: absolute; left: 16mm; right: 16mm; top: 10mm; height: 12mm; display: flex; align-items: center; }
.header .hl { display: flex; align-items: center; gap: 2mm; }
.header .hl svg { width: 8mm; height: 8mm; }
.header .t1 { font-size: 10.5pt; font-weight: bold; color: #333E48; }
.header .t2 { font-size: 6.5pt; color: #9AA5B1; letter-spacing: .6mm; }
.header .hr { margin-left: auto; font-size: 10.5pt; color: #8A94A6; }
.footer { position: absolute; left: 0; right: 0; bottom: 8mm; text-align: center; font-size: 9pt; color: #333; }
h1 { font-size: 16pt; color: #1667B8; margin: 4mm 0 3mm; }
h2 { font-size: 13pt; color: #1667B8; margin: 4mm 0 2.5mm; }
h3 { font-size: 11.5pt; color: #1667B8; margin: 3mm 0 2mm; }
p.para { font-size: 10.5pt; line-height: 1.8; text-indent: 2em; margin: 0 0 2mm; text-align: justify; }
.scope { font-size: 9pt; color: #8A94A6; text-align: center; margin: 1mm 0 2mm; }
.note { font-size: 9pt; color: #8A94A6; margin: 1.5mm 0; }
.chart { text-align: center; margin: 2mm 0; }
.chart .ctitle { font-size: 11pt; font-weight: bold; color: #333; margin-bottom: 1mm; }
.em-b { color: #1667B8; } .em-r { color: #E64545; }
table { border-collapse: collapse; width: 100%; font-size: 10pt; margin: 1mm 0; }
th { background: #EFF3F8; font-weight: bold; }
th, td { border: 1px solid #B9C2CC; padding: 1.6mm 2mm; text-align: left; vertical-align: top; }
td.num, th.num { text-align: right; }
.ttitle { font-size: 11pt; font-weight: bold; text-align: center; margin: 2mm 0 1mm; }
.cover-wave { position: absolute; inset: 0; width: 210mm; height: 297mm; }
.cv-logo { position: absolute; left: 16mm; top: 16mm; display: flex; gap: 4mm; align-items: flex-start; }
.cv-logo svg { width: 16mm; height: 16mm; }
.cv-logo .t1 { font-size: 24pt; font-weight: bold; color: #333E48; line-height: 1.1; }
.cv-logo .t2 { font-size: 11pt; color: #9AA5B1; letter-spacing: 1.2mm; }
.cv-title { position: absolute; left: 16mm; top: 52mm; font-size: 40pt; font-weight: bold; color: #0B5CAD; }
.cv-subject { position: absolute; left: 16mm; top: 80mm; font-size: 20pt; color: #333; }
.cv-nav { position: absolute; left: 16mm; top: 93mm; font-size: 12pt; color: #9AA5B1; }
.cv-nav span { margin-right: 6mm; }
.cv-rule { position: absolute; left: 0; top: 100mm; width: 120mm; height: .8mm; background: #D9DDE3; }
.cv-disc { position: absolute; left: 16mm; top: 210mm; width: 178mm; font-size: 11pt; color: #6B7280; line-height: 1.9; }
"""


def header_dom(logo_svg):
    return (f'<div class="header"><div class="hl">{logo_svg}'
            '<div><div class="t1">行业洞察</div><div class="t2">产业数据服务平台</div></div></div>'
            '<div class="hr">产业洞察报告</div></div>')


def cover_dom(spec, logo_svg, wave_svg):
    nav = "".join(f"<span>{esc(s)}</span>" for s in spec.get("nav", []))
    asof = spec.get("as_of_cn", "")
    return (f'<div class="cover-wave">{wave_svg}</div>'
            f'<div class="cv-logo">{logo_svg}<div><div class="t1">行业洞察</div>'
            f'<div class="t2">产业数据服务平台</div></div></div>'
            f'<div class="cv-title">产业洞察报告</div>'
            f'<div class="cv-subject">{esc(spec["region_name"])}{esc(spec["industry_name"])}</div>'
            f'<div class="cv-nav">{nav}</div><div class="cv-rule"></div>'
            f'<div class="cv-disc">报告编号：{esc(spec.get("report_no", ""))}　版本：v1<br>'
            f'本报告生成时间为 {esc(asof)}，报告内容基于合法取得的信息编制而成，仅供参考使用。</div>')


def back_dom(logo_svg, wave_svg, qr_svg):
    return (f'<div class="cover-wave" style="transform:scaleY(-1)">{wave_svg}</div>'
            f'<div style="position:absolute;left:0;right:0;top:118mm;text-align:center">{logo_svg.replace("width", "data-w", 0) if False else ""}'
            f'<div style="display:flex;justify-content:center;align-items:center;gap:4mm">'
            f'<span style="width:20mm;height:20mm;display:inline-block">{logo_svg}</span>'
            f'<span style="text-align:left"><span style="font-size:22pt;font-weight:bold;color:#333E48">行业洞察</span><br>'
            f'<span style="font-size:12pt;color:#9AA5B1;letter-spacing:1mm">产业数据服务平台</span></span></div>'
            f'<div style="margin-top:4mm;font-size:14pt;color:#9C27B0;text-decoration:underline">xhzjds.cnfic.com.cn</div></div>'
            f'<div style="position:absolute;left:16mm;right:16mm;bottom:16mm;display:flex;gap:6mm;align-items:center">'
            f'<span style="width:22mm;height:22mm">{qr_svg}</span>'
            f'<span style="flex:1"><span style="font-size:12pt;font-weight:bold">中国经济信息社上海总部</span>'
            f'<hr style="border:none;border-top:1px solid #333;margin:2mm 0">'
            f'<span style="font-size:10pt">◎ 上海市浦东新区东园路18号中国金融信息中心10层　　✉ ceissh@xinhua.org</span></span></div>')


def block_dom(b, charts, chart_svgs):
    t = b["t"]
    if t == "h1":
        return f"<h1>{esc(b['text'])}</h1>"
    if t == "h2":
        return f"<h2>{esc(b['text'])}</h2>"
    if t == "h3":
        return f"<h3>{esc(b['text'])}</h3>"
    if t == "para":
        return f'<p class="para">{inline(b["text"])}</p>'
    if t == "scope":
        return f'<div class="scope">截至：{esc(b["as_of"])}　　数据来源：{esc(b["source"])}</div>'
    if t == "note":
        return f'<div class="note">{inline(b["text"])}</div>'
    if t == "chart":
        c = charts[b["chart_id"]]
        return (f'<div class="chart"><div class="ctitle">{esc(c["title"])}</div>'
                f'<div class="scope">截至：{esc(c["as_of"])}　　数据来源：{esc(c["source"])}</div>'
                f'{chart_svgs[b["chart_id"]]}</div>')
    if t == "table":
        aligns = b.get("aligns", [])
        th = "".join(f'<th class="{aligns[i] if i < len(aligns) else ""}">{esc(h)}</th>'
                     for i, h in enumerate(b["headers"]))
        trs = ""
        for row in b["rows"]:
            tds = "".join(f'<td class="{aligns[i] if i < len(aligns) else ""}">{inline(c)}</td>'
                          for i, c in enumerate(row))
            trs += f"<tr>{tds}</tr>"
        title = f'<div class="ttitle">{esc(b["title"])}</div>' if b.get("title") else ""
        note = f'<div class="note">{esc(b["note"])}</div>' if b.get("note") else ""
        return f'{title}<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>{note}'
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rd = Path(a.run_dir)
    spec = json.loads((rd / "spec.json").read_text(encoding="utf-8"))
    blocks = json.loads((rd / "blocks.json").read_text(encoding="utf-8"))
    charts = json.loads((rd / "charts" / "charts.json").read_text(encoding="utf-8"))
    assets = Path(__file__).resolve().parent.parent / "assets"
    logo = (assets / "logo.svg").read_text(encoding="utf-8").replace('<svg ', '<svg width="100%" height="100%" ', 1)
    wave = (assets / "cover_wave.svg").read_text(encoding="utf-8")
    qr = (assets / "qr_placeholder.svg").read_text(encoding="utf-8")
    chart_svgs = {cid: (rd / "charts" / f"{cid}.svg").read_text(encoding="utf-8") for cid in charts}

    pages = pack(blocks, charts)
    out = [f"<html><head><meta charset='utf-8'><title>{esc(spec.get('title', '产业洞察报告'))}</title>"
           f"<style>{CSS}</style></head><body>"]
    out.append(f'<section class="page">{cover_dom(spec, logo, wave)}</section>')
    for pi, page in enumerate(pages, 1):
        dom = "".join(block_dom(b, charts, chart_svgs) for b in page)
        out.append(f'<section class="page">{header_dom(logo)}<div class="content">{dom}</div>'
                   f'<div class="footer">{pi}</div></section>')
    out.append(f'<section class="page">{back_dom(logo, wave, qr)}</section>')
    out.append("</body></html>")
    Path(a.out).write_text("".join(out), encoding="utf-8")
    print(json.dumps({"pages": len(pages) + 2, "out": a.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
