import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRIPTS = ROOT / "skills" / "public" / "industry-insight-report" / "scripts"
FIXTURE = SCRIPTS / "fixtures" / "sample_shanghai_brain.json"


def test_e2e_fixture_pipeline(tmp_path):
    out = tmp_path / "run"
    r = subprocess.run([sys.executable, str(SCRIPTS / "run_report.py"),
                        "--industry-code", "BRAINLIKE", "--region-code", "310000",
                        "--fixture", str(FIXTURE), "--out", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "report.md").exists() and (out / "report.html").exists()
    assert json.loads((out / "validation_report.json").read_text(encoding="utf-8"))["passed"]
    assert json.loads((out / "check_report.json").read_text(encoding="utf-8"))["passed"]
    prog = json.loads((out / "progress.json").read_text(encoding="utf-8"))
    assert prog["S3.5"]["status"] == "passed" and prog["S4.5"]["status"] == "passed"
    assert prog["S5"]["status"] in ("passed", "degraded")  # 无 PDF 引擎环境允许降级


def test_rerun_is_idempotent(tmp_path):
    out = tmp_path / "run"
    for _ in range(2):
        r = subprocess.run([sys.executable, str(SCRIPTS / "run_report.py"),
                            "--industry-code", "BRAINLIKE", "--region-code", "310000",
                            "--fixture", str(FIXTURE), "--out", str(out)],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
