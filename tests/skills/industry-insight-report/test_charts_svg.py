import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SKILL = ROOT / "skills" / "public" / "industry-insight-report"
sys.path.insert(0, str(SKILL / "scripts"))
import charts_svg  # noqa: E402

THEME = json.loads((SKILL / "assets" / "theme.json").read_text(encoding="utf-8"))


def _specs():
    return [
        {"type": "score_bar", "total": 93.49, "year": 2025, "grade": "A", "grade_index": 4,
         "rank_national": [1, 337], "rank_region": [1, 77]},
        {"type": "radar", "dims": [{"name": f"d{i}", "score": 80 + i, "grade": "A"} for i in range(6)]},
        {"type": "tree", "blocks": [{"name": "上游", "count": 5, "root": "根", "mids": [{"name": "中", "leaves": ["叶1", "叶2"]}]}]},
        {"type": "bar_grouped", "categories": ["2024", "2025"], "series": [{"name": "a", "values": [1, 2]}, {"name": "b", "values": [3, 4]}]},
        {"type": "bar_stacked", "categories": ["2024", "2025"], "series": [{"name": "a", "values": [1, 2]}, {"name": "b", "values": [3, 4]}]},
        {"type": "dual_bar_line", "categories": ["2024", "2025"], "bars": {"name": "金额", "values": [1, 2]}, "line": {"name": "件数", "values": [3, 4]}},
        {"type": "line_index", "categories": ["2024", "2025"], "series": [{"name": "a", "values": [100, 110]}]},
        {"type": "donut", "items": [{"name": f"s{i}", "count": i + 1, "share": 10} for i in range(10)], "center_label": "x"},
        {"type": "pyramid", "levels": [{"name": "a", "count": 1, "share": 10}, {"name": "b", "count": 2, "share": 90}]},
        {"type": "hbar", "items": [{"name": "a", "value": 3}, {"name": "b", "value": 1}]},
        {"type": "bubble_grid", "rows": ["x", "y"], "cols": ["10分", "9分"], "matrix": [[1, 2], [3, 0]]},
    ]


def test_all_renderers_produce_svg():
    for spec in _specs():
        svg, h = charts_svg.render(spec, THEME)
        assert svg.startswith("<svg") and svg.endswith("</svg>"), spec["type"]
        assert h > 0
        assert "NaN" not in svg and "undefined" not in svg


def test_donut_merges_over_eight():
    svg, _ = charts_svg.render({"type": "donut", "items": [{"name": f"s{i}", "count": 1, "share": 10} for i in range(12)]}, THEME)
    assert "其他" in svg
