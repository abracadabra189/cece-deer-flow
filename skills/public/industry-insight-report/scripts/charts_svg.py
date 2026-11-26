"""内置 SVG 图表渲染器（离线、无 JS 依赖、打印稳定）。

每个 render_* 接收 (spec, theme) 返回 (svg_str, height_mm)。
spec schema 见 references/chart-map.md；通用字段: id/type/title。
"""
from __future__ import annotations

import math

W = 680  # px canvas width
MM_W = 170.0  # embed width in mm


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _svg(inner: str, h_px: int, w_mm: float = MM_W) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h_px}" '
            f'width="{w_mm}mm" role="img">{inner}</svg>')


def _font(theme, size, bold=False, fill="#333333"):
    fam = theme["fonts"]["cn"]
    b = ' font-weight="bold"' if bold else ''
    return f'font-family="{esc(fam)}" font-size="{size}"{b} fill="{fill}"'


def _text(x, y, s, theme, size=11, bold=False, fill="#333333", anchor="start"):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
            f'{_font(theme, size, bold, fill)}>{esc(s)}</text>')


def _line(x1, y1, x2, y2, color="#D9DDE3", w=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}"{d}/>'


def _rect(x, y, w, h, fill, rx=0):
    return f'<rect x="{x}" y="{y}" width="{max(w,0)}" height="{max(h,0)}" fill="{fill}" rx="{rx}"/>'


def nice_ticks(maxv: float, n: int = 5):
    if maxv <= 0:
        return [0, 1]
    raw = maxv / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if maxv / step <= n:
            break
    ticks = []
    v = 0.0
    while v < maxv * 1.0001:
        ticks.append(round(v, 6))
        v += step
    if ticks[-1] < maxv:
        ticks.append(round(ticks[-1] + step, 6))
    return ticks


def _fmt(v):
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _legend(items, theme, y, h=W):
    """items: [(label, color)] 置底单行/自动换行"""
    out, x, = [], 40
    for label, color in items:
        need = 18 + 7 * len(str(label))
        if x + need > h - 20:
            x, y = 40, y + 18
        out.append(_rect(x, y - 9, 14, 9, color, rx=2))
        out.append(_text(x + 18, y, label, theme, 10, fill="#666666"))
        x += need + 14
    return "".join(out), y + 20


def _y_axis(x0, y0, y1, ticks, maxv, theme, unit=""):
    out = [_line(x0, y0, x0, y1, "#BBBBBB")]
    span = y1 - y0
    top = ticks[-1] if ticks[-1] > 0 else 1
    for t in ticks:
        y = y1 - span * (t / top)
        out.append(_line(x0, y, W - 30, y, "#E3E7EC"))
        out.append(_text(x0 - 6, y + 3, _fmt(t), theme, 9.5, fill="#8A94A6", anchor="end"))
    if unit:
        out.append(_text(x0 - 6, y0 - 8, unit, theme, 9.5, fill="#8A94A6", anchor="end"))
    return "".join(out), top


# ---------------------------------------------------------------- renderers

def render_score_bar(spec, theme):
    grades = ["较差", "较低", "一般", "良好", "优秀"]
    gc = theme["grade_colors"]
    h = 250
    inner = [_text(W / 2, 30, spec.get("title", "综合评分"), theme, 15, bold=True, anchor="middle")]
    inner.append(_text(W / 2, 78, f"{spec['total']:.2f}", theme, 40, bold=True, anchor="middle"))
    inner.append(_text(W / 2, 102, f"评分年度：{spec.get('year', '')}年", theme, 13, fill="#9AA5B1", anchor="middle"))
    x0, bw, y = 60, (W - 120) / 5, 128
    gi = spec.get("grade_index", 4)
    for i, g in enumerate(grades):
        inner.append(_rect(x0 + i * bw + 2, y, bw - 4, 8, gc[i], rx=2))
        inner.append(_text(x0 + i * bw + bw / 2, y + 28, g, theme, 11, fill="#555555", anchor="middle"))
    mx = x0 + gi * bw + bw / 2
    inner.append(_rect(mx - 11, y - 7, 22, 22, gc[gi], rx=4))
    inner.append(_text(mx, y + 9, spec.get("grade", "A"), theme, 13, bold=True, fill="#ffffff", anchor="middle"))
    rn, rr = spec.get("rank_national", ["-", "-"]), spec.get("rank_region", ["-", "-"])
    inner.append(_text(W / 2 - 90, y + 66, spec.get("rank_national_label", "全国城市排名"), theme, 10.5, fill="#8A94A6", anchor="middle"))
    inner.append(_text(W / 2 - 90, y + 84, f"{rn[0]}/{rn[1]}", theme, 11, anchor="middle"))
    inner.append(_text(W / 2 + 90, y + 66, spec.get("rank_region_label", "区域排名"), theme, 10.5, fill="#8A94A6", anchor="middle"))
    inner.append(_text(W / 2 + 90, y + 84, f"{rr[0]}/{rr[1]}", theme, 11, anchor="middle"))
    return _svg("".join(inner), h), 62


def render_radar(spec, theme):
    dims = spec["dims"]
    n = len(dims)
    cx, cy, R = W / 2, 165, 105
    h = 340
    inner = []
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{cx + R * ring * math.cos(2 * math.pi * i / n - math.pi / 2)},"
                       f"{cy + R * ring * math.sin(2 * math.pi * i / n - math.pi / 2)}" for i in range(n))
        inner.append(f'<polygon points="{pts}" fill="none" stroke="#E3E7EC"/>')
    for i in range(n):
        a = 2 * math.pi * i / n - math.pi / 2
        inner.append(_line(cx, cy, cx + R * math.cos(a), cy + R * math.sin(a), "#D9DDE3"))
    vals = [min(d["score"], 100) / 100 for d in dims]
    pts = " ".join(f"{cx + R * v * math.cos(2 * math.pi * i / n - math.pi / 2)},"
                   f"{cy + R * v * math.sin(2 * math.pi * i / n - math.pi / 2)}" for i, v in enumerate(vals))
    inner.append(f'<polygon points="{pts}" fill="#5B8FF9" fill-opacity="0.25" stroke="#5B8FF9" stroke-width="1.6"/>')
    for i, d in enumerate(dims):
        a = 2 * math.pi * i / n - math.pi / 2
        lx, ly = cx + (R + 26) * math.cos(a), cy + (R + 26) * math.sin(a)
        anchor = "middle" if abs(math.cos(a)) < 0.3 else ("start" if math.cos(a) > 0 else "end")
        inner.append(_text(lx, ly - 2, d["name"], theme, 10.5, fill="#555555", anchor=anchor))
        inner.append(_text(lx, ly + 12, f"{d.get('grade', '')}|{d['score']:.2f}", theme, 10, fill="#8A94A6", anchor=anchor))
    return _svg("".join(inner), h), 90


def render_tree(spec, theme):
    blocks = spec["blocks"]
    rows = sum(len(b["mids"]) for b in blocks) + len(blocks) * 1.4
    rh = 30
    h = int(rows * rh) + 20
    inner, y = [], 10
    colors = ["#5B8FF9", "#30BF78", "#E88CA5"]
    for bi, b in enumerate(blocks):
        inner.append(_text(20, y + 14, f"{b['name']}（{b.get('count', '')} 家企业）", theme, 13, bold=True, fill=colors[bi % 3]))
        y += rh * 0.9
        bx0, bx1, bx2 = 40, 210, 400
        n = len(b["mids"])
        root_y = y + (n - 1) * rh / 2
        inner.append(_text(bx0, root_y + 4, b["root"], theme, 10, fill="#777777"))
        for mi, m in enumerate(b["mids"]):
            my = y + mi * rh
            inner.append(_line(bx0 + 8 + 6.2 * len(b["root"]), root_y, bx1, my, "#C9D2DC"))
            inner.append(_text(bx1, my + 4, m["name"], theme, 10, fill="#555555"))
            leaves = "，".join(m.get("leaves", []))
            if len(leaves) > 42:
                leaves = leaves[:41] + "…"
            inner.append(_line(bx1 + 6.2 * len(m["name"]), my, bx2, my, "#C9D2DC"))
            inner.append(_text(bx2, my + 4, leaves, theme, 9, fill="#8A94A6"))
        y += n * rh + rh * 0.5
    return _svg("".join(inner), h), min(120, h * 0.25)  # svg 宽固定 170mm → 0.25mm/px


def render_bar_grouped(spec, theme):
    cats, series = spec["categories"], spec["series"]
    h = 300
    y0, y1, x0 = 30, 240, 60
    maxv = max(max(s["values"]) for s in series)
    ticks = nice_ticks(maxv)
    ax, top = _y_axis(x0, y0, y1, ticks, maxv, theme, spec.get("unit", ""))
    inner = [ax]
    gw = (W - x0 - 30) / len(cats)
    bw = min(26, gw / (len(series) + 1))
    pal = theme["chart_palette"]
    for ci, c in enumerate(cats):
        inner.append(_text(x0 + gw * ci + gw / 2, y1 + 16, c, theme, 9.5, fill="#8A94A6", anchor="middle"))
        for si, s in enumerate(series):
            v = s["values"][ci]
            bh = (y1 - y0) * (v / top)
            x = x0 + gw * ci + gw / 2 - bw * len(series) / 2 + si * bw
            inner.append(_rect(x, y1 - bh, bw - 3, bh, s.get("color", pal[si % len(pal)]), rx=1.5))
    lg, ly = _legend([(s["name"], s.get("color", pal[i % len(pal)])) for i, s in enumerate(series)], theme, y1 + 40)
    inner.append(lg)
    return _svg("".join(inner), ly + 6), 82


def render_bar_stacked(spec, theme):
    cats, series = spec["categories"], spec["series"]
    h = 320
    y0, y1, x0 = 30, 250, 60
    totals = [sum(s["values"][i] for s in series) for i in range(len(cats))]
    ticks = nice_ticks(max(totals))
    ax, top = _y_axis(x0, y0, y1, ticks, max(totals), theme, spec.get("unit", ""))
    inner = [ax]
    gw = (W - x0 - 30) / len(cats)
    bw = min(34, gw * 0.55)
    pal = theme["chart_palette"]
    for ci, c in enumerate(cats):
        inner.append(_text(x0 + gw * ci + gw / 2, y1 + 16, c, theme, 9.5, fill="#8A94A6", anchor="middle"))
        acc = 0
        for si, s in enumerate(series):
            v = s["values"][ci]
            if v <= 0:
                continue
            bh = (y1 - y0) * (v / top)
            ya = (y1 - y0) * (acc / top)
            inner.append(_rect(x0 + gw * ci + (gw - bw) / 2, y1 - ya - bh, bw, bh, s.get("color", pal[si % len(pal)])))
            acc += v
    lg, ly = _legend([(s["name"], s.get("color", pal[i % len(pal)])) for i, s in enumerate(series)], theme, y1 + 40)
    inner.append(lg)
    return _svg("".join(inner), ly + 6), 88


def render_dual_bar_line(spec, theme):
    cats, bars, line = spec["categories"], spec["bars"], spec["line"]
    h = 320
    y0, y1, x0 = 30, 250, 64
    tb, tl = nice_ticks(max(bars["values"])), nice_ticks(max(line["values"]))
    ax, topb = _y_axis(x0, y0, y1, tb, max(bars["values"]), theme, spec.get("unit_left", "(亿元)"))
    inner = [ax]
    span = y1 - y0
    topl = tl[-1]
    for t in tl:
        y = y1 - span * (t / topl)
        inner.append(_text(W - 26, y + 3, _fmt(t), theme, 9.5, fill="#8A94A6"))
    inner.append(_text(W - 26, y0 - 8, spec.get("unit_right", "(次)"), theme, 9.5, fill="#8A94A6", anchor="end"))
    gw = (W - x0 - 44) / len(cats)
    bw = min(30, gw * 0.5)
    for ci, c in enumerate(cats):
        inner.append(_text(x0 + gw * ci + gw / 2, y1 + 16, c, theme, 9, fill="#8A94A6", anchor="middle"))
        v = bars["values"][ci]
        bh = span * (v / topb)
        inner.append(_rect(x0 + gw * ci + (gw - bw) / 2, y1 - bh, bw, bh, "#5B8FF9", rx=1.5))
    pts = [(x0 + gw * ci + gw / 2, y1 - span * (line["values"][ci] / topl)) for ci in range(len(cats))]
    inner.append('<polyline points="' + " ".join(f"{x},{y}" for x, y in pts) +
                 '" fill="none" stroke="#F6903D" stroke-width="2"/>')
    for x, y in pts:
        inner.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#F6903D"/>')
    lg, ly = _legend([(bars["name"], "#5B8FF9"), (line["name"], "#F6903D")], theme, y1 + 40)
    inner.append(lg)
    return _svg("".join(inner), ly + 6), 88


def render_line_index(spec, theme):
    cats, series = spec["categories"], spec["series"]
    h = 300
    y0, y1, x0 = 30, 240, 60
    allv = [v for s in series for v in s["values"] if v is not None] + [100]
    ticks = nice_ticks(max(allv))
    ax, top = _y_axis(x0, y0, y1, ticks, max(allv), theme, spec.get("unit", ""))
    inner = [ax]
    span = y1 - y0
    y100 = y1 - span * (100 / top)
    inner.append(_line(x0, y100, W - 30, y100, "#BBBBBB", dash="4,3"))
    gw = (W - x0 - 30) / len(cats)
    pal = ["#F6903D", "#A3B8F0"]
    for ci, c in enumerate(cats):
        inner.append(_text(x0 + gw * ci + gw / 2, y1 + 16, c, theme, 9.5, fill="#8A94A6", anchor="middle"))
    for si, s in enumerate(series):
        pts = [(x0 + gw * ci + gw / 2, y1 - span * (v / top)) for ci, v in enumerate(s["values"]) if v is not None]
        if pts:
            inner.append('<polyline points="' + " ".join(f"{x},{y}" for x, y in pts) +
                         f'" fill="none" stroke="{s.get("color", pal[si % 2])}" stroke-width="2"/>')
    lg, ly = _legend([(s["name"], s.get("color", pal[i % 2])) for i, s in enumerate(series)], theme, y1 + 40)
    inner.append(lg)
    return _svg("".join(inner), ly + 6), 82


def render_donut(spec, theme):
    items = spec["items"]
    if len(items) > 8:
        head, tail = items[:7], items[7:]
        items = head + [{"name": "其他", "count": sum(i["count"] for i in tail),
                         "share": round(sum(i.get("share", 0) for i in tail), 2)}]
    cx, cy, R, r = W / 2, 160, 95, 52
    h = 340
    total = sum(i["count"] for i in items) or 1
    pal = theme["chart_palette"]
    inner = [_text(cx, cy - 2, spec.get("center_label", ""), theme, 11, fill="#666666", anchor="middle"),
             _text(cx, cy + 14, spec.get("center_value", ""), theme, 11, bold=True, anchor="middle")]
    a = -math.pi / 2
    for i, it in enumerate(items):
        frac = it["count"] / total
        a2 = a + frac * 2 * math.pi
        gap = 0.02
        large = 1 if (a2 - a - gap) > math.pi else 0
        x1, y1 = cx + R * math.cos(a + gap / 2), cy + R * math.sin(a + gap / 2)
        x2, y2 = cx + R * math.cos(a2 - gap / 2), cy + R * math.sin(a2 - gap / 2)
        x3, y3 = cx + r * math.cos(a2 - gap / 2), cy + r * math.sin(a2 - gap / 2)
        x4, y4 = cx + r * math.cos(a + gap / 2), cy + r * math.sin(a + gap / 2)
        inner.append(f'<path d="M{x1},{y1} A{R},{R} 0 {large} 1 {x2},{y2} L{x3},{y3} '
                     f'A{r},{r} 0 {large} 0 {x4},{y4} Z" fill="{pal[i % len(pal)]}"/>')
        am = (a + a2) / 2
        lx, ly = cx + (R + 16) * math.cos(am), cy + (R + 16) * math.sin(am)
        anchor = "start" if math.cos(am) >= 0 else "end"
        inner.append(_text(lx, ly, it["name"], theme, 10, fill="#555555", anchor=anchor))
        inner.append(_text(lx, ly + 13, f"{it['count']:,}家,{it.get('share', 0):.2f}%"
                           if spec.get("unit_word") == "家" else f"{it['count']:,},{it.get('share', 0):.2f}%",
                           theme, 9.5, fill="#8A94A6", anchor=anchor))
        a = a2
    return _svg("".join(inner), h), 92


def render_pyramid(spec, theme):
    levels = spec["levels"]
    h = 90 * len(levels) + 60
    cx, top = W / 2 - 60, 20
    maxw, rh = 300, (h - 60) / len(levels)
    pal = ["#0E4E7E", "#1F77B4", "#5B9BD5", "#A8CBE8", "#CFE2F3"]
    inner = []
    for i, lv in enumerate(levels):
        w_top = maxw * (0.25 + 0.75 * (i / len(levels)))
        w_bot = maxw * (0.25 + 0.75 * ((i + 1) / len(levels)))
        y = top + i * rh
        inner.append(f'<polygon points="{cx - w_top / 2},{y} {cx + w_top / 2},{y} '
                     f'{cx + w_bot / 2},{y + rh - 2} {cx - w_bot / 2},{y + rh - 2}" fill="{pal[i % len(pal)]}"/>')
        ly = y + rh / 2
        inner.append(_line(cx + w_bot / 2, ly, cx + w_bot / 2 + 26, ly, "#999999"))
        inner.append(_text(cx + w_bot / 2 + 30, ly - 2, lv["name"], theme, 10, bold=True, fill="#555555"))
        inner.append(_text(cx + w_bot / 2 + 30, ly + 12, f"{lv['count']:,}家, {lv.get('share', 0):.2f}%", theme, 9.5, fill="#8A94A6"))
    return _svg("".join(inner), h), min(110, h * 0.25)


def render_hbar(spec, theme):
    items = spec["items"]
    rh = 26
    h = len(items) * rh + 60
    x0, x1 = 120, W - 90
    maxv = max(i["value"] for i in items) or 1
    inner = []
    for i, it in enumerate(items):
        y = 20 + i * rh
        inner.append(_text(x0 - 8, y + 13, it["name"], theme, 10, fill="#555555", anchor="end"))
        bw = (x1 - x0) * (it["value"] / maxv)
        inner.append(_rect(x0, y + 3, bw, 14, "#5B8FF9", rx=2))
        inner.append(_text(x0 + bw + 6, y + 14, _fmt(it["value"]), theme, 9.5, fill="#8A94A6"))
    inner.append(_line(x0, 14, x0, 20 + len(items) * rh - 6, "#BBBBBB"))
    return _svg("".join(inner), h), min(120, h * 0.25)


def render_bubble_grid(spec, theme):
    rows, cols, matrix = spec["rows"], spec["cols"], spec["matrix"]
    cw, ch = 56, 78
    x0, y0 = 130, 30
    h = y0 + len(rows) * ch + 40
    maxv = max(max(r) for r in matrix) or 1
    pal = ["#A3B8F0", "#30BF78", "#A8D8EA"]
    inner = []
    for ci, c in enumerate(cols):
        inner.append(_text(x0 + ci * cw + cw / 2, y0 + len(rows) * ch + 18, c, theme, 10, fill="#8A94A6", anchor="middle"))
    for ri, rname in enumerate(rows):
        inner.append(_text(x0 - 12, y0 + ri * ch + ch / 2 + 4, rname, theme, 10.5, fill="#555555", anchor="end"))
        for ci in range(len(cols)):
            v = matrix[ri][ci]
            if not v:
                continue
            r = 6 + 20 * math.sqrt(v / maxv)
            inner.append(f'<circle cx="{x0 + ci * cw + cw / 2}" cy="{y0 + ri * ch + ch / 2}" '
                         f'r="{r}" fill="{pal[ri % len(pal)]}" fill-opacity="0.85"/>')
        inner.append(_line(x0 + 0, y0 + ri * ch + ch / 2, x0 + len(cols) * cw, y0 + ri * ch + ch / 2, "#EDEFF2"))
    return _svg("".join(inner), h), min(110, h * 0.25)


RENDERERS = {
    "score_bar": render_score_bar,
    "radar": render_radar,
    "tree": render_tree,
    "bar_grouped": render_bar_grouped,
    "bar_stacked": render_bar_stacked,
    "dual_bar_line": render_dual_bar_line,
    "line_index": render_line_index,
    "donut": render_donut,
    "pyramid": render_pyramid,
    "hbar": render_hbar,
    "bubble_grid": render_bubble_grid,
}


def render(spec, theme):
    fn = RENDERERS.get(spec["type"])
    if fn is None:
        raise ValueError(f"unknown chart type: {spec['type']}")
    return fn(spec, theme)
