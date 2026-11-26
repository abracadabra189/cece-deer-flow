import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRIPTS = ROOT / "skills" / "public" / "industry-insight-report" / "scripts"


def _write_data(dirp: Path):
    dirp.mkdir(parents=True, exist_ok=True)
    score = {"dataset": "score", "as_of": "2026-11-19", "source_cmd": "fixture", "fetched_at": "t",
             "unit": "", "rows": [{"total": 90.5, "year": 2025, "grade": "A", "grade_index": 4,
                                   "rank_national": [1, 337], "rank_region": [1, 77],
                                   "dims": [{"name": "产业规模", "score": 91.0, "grade": "A"}]}]}
    cap = {"dataset": "ent_capital", "as_of": "2026-11-19", "source_cmd": "fixture", "fetched_at": "t",
           "unit": "", "rows": [{"name": "100万元以下", "count": 55, "share": 50.0},
                                {"name": "100万~500万元", "count": 45, "share": 50.0}]}
    (dirp / "score.json").write_text(json.dumps(score, ensure_ascii=False), encoding="utf-8")
    (dirp / "ent_capital.json").write_text(json.dumps(cap, ensure_ascii=False), encoding="utf-8")
    chain = {"dataset": "chain", "as_of": "2026-11-19", "source_cmd": "fixture", "fetched_at": "t",
             "unit": "", "rows": [{"blocks": [{"name": "上游", "count": 5, "root": "根层",
                                                "mids": [{"name": "环节", "leaves": ["叶"]}]}]}]}
    trend = {"dataset": "ent_trend", "as_of": "2026-11-19", "source_cmd": "fixture", "fetched_at": "t",
             "unit": "", "rows": [{"year": 2025, "stock": 100, "new_reg": 10},
                                  {"year": 2026, "stock": 110, "new_reg": 10}]}
    (dirp / "chain.json").write_text(json.dumps(chain, ensure_ascii=False), encoding="utf-8")
    (dirp / "ent_trend.json").write_text(json.dumps(trend, ensure_ascii=False), encoding="utf-8")
    (dirp / "data_manifest.json").write_text(json.dumps({"as_of": "2026-11-19", "sources": {}, "limitations": []}), encoding="utf-8")


def test_validate_pass(tmp_path):
    _write_data(tmp_path / "data")
    md = tmp_path / "report.md"
    md.write_text("# t\n综合评分为 90.5 分，企业 55 家，占比 50.00%，排名 1/337。\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate_data.py"), "--data-dir", str(tmp_path / "data"),
                        "--md", str(md), "--out", str(tmp_path / "v.json")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))["passed"]


def test_validate_l3_blocks_fabricated_number(tmp_path):
    _write_data(tmp_path / "data")
    md = tmp_path / "report.md"
    md.write_text("# t\n综合评分为 90.5 分，企业规模达 12345.67 家。\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate_data.py"), "--data-dir", str(tmp_path / "data"),
                        "--md", str(md), "--out", str(tmp_path / "v.json")], capture_output=True, text=True)
    rep = json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))
    assert r.returncode == 1 and not rep["passed"]
    assert any(f["level"] == "L3" for f in rep["failures"])


def test_validate_l1_blocks_p0(tmp_path):
    _write_data(tmp_path / "data")
    bad = json.loads((tmp_path / "data" / "score.json").read_text(encoding="utf-8"))
    del bad["as_of"]
    (tmp_path / "data" / "score.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    md = tmp_path / "report.md"
    md.write_text("# t\n综合评分为 90.5 分。\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate_data.py"), "--data-dir", str(tmp_path / "data"),
                        "--md", str(md), "--out", str(tmp_path / "v.json")], capture_output=True, text=True)
    assert r.returncode == 1
