import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRIPTS = ROOT / "skills" / "public" / "industry-insight-report" / "scripts"


def _run_dir(tmp_path: Path) -> Path:
    rd = tmp_path / "run"
    (rd / "charts").mkdir(parents=True)
    spec = {"region_name": "上海市", "industry_name": "测试产业", "as_of": "2026-11-19",
            "as_of_cn": "2026 年 11 月 19 日", "generated_cn": "2026 年 11 月 20 日",
            "report_no": "T-310000-2026-11-19", "nav": ["产业评分"], "title": "产业洞察报告"}
    rows = [[str(i), f"企业{i}", "上海市/浦东新区", "100 万元", "3", "80.00"] for i in range(40)]
    blocks = [
        {"t": "h1", "text": "一、产业评分"},
        {"t": "para", "text": "事实段。"},
        {"t": "chart", "chart_id": "c1", "type": "score_bar", "dataset": "score", "title": "综合评分"},
        {"t": "table", "title": "Top 表", "headers": ["排名", "企业名称", "所属地区", "注册资本", "授权专利数", "企业评分"],
         "rows": rows, "aligns": ["num", "", "", "num", "num", "num"]},
    ]
    (rd / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    (rd / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    (rd / "charts" / "charts.json").write_text(json.dumps(
        {"c1": {"title": "综合评分", "as_of": "2026-11-19", "source": "行业洞察", "h_mm": 62, "type": "score_bar"}},
        ensure_ascii=False), encoding="utf-8")
    (rd / "charts" / "c1.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" role="img" viewBox="0 0 680 250"></svg>', encoding="utf-8")
    return rd


def test_build_html_pagination_and_tables(tmp_path):
    rd = _run_dir(tmp_path)
    out = rd / "report.html"
    r = subprocess.run([sys.executable, str(SCRIPTS / "build_html.py"), "--run-dir", str(rd), "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = out.read_text(encoding="utf-8")
    pages = html.count('class="page"')
    assert pages >= 4  # 封面 + >=2 内容页（40 行表跨页） + 封底
    assert html.count('class="header"') == pages - 2
    assert html.count('class="footer"') == pages - 2
    assert html.count("<table>") == html.count("<thead>")  # 跨页表每页重复表头
    assert "http" not in html.replace("http-equiv", "") or 'src="http' not in html
    assert html.count('role="img"') == 1


def test_check_html_passes(tmp_path):
    rd = _run_dir(tmp_path)
    out = rd / "report.html"
    subprocess.run([sys.executable, str(SCRIPTS / "build_html.py"), "--run-dir", str(rd), "--out", str(out)],
                   capture_output=True, text=True, check=True)
    r = subprocess.run([sys.executable, str(SCRIPTS / "check_html.py"), "--html", str(out),
                        "--run-dir", str(rd), "--out", str(rd / "check.json")], capture_output=True, text=True)
    rep = json.loads((rd / "check.json").read_text(encoding="utf-8"))
    assert r.returncode == 0 and rep["passed"], rep
