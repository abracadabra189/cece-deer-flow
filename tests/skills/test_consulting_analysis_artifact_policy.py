from __future__ import annotations

from pathlib import Path
import unittest


SKILL_PATH = Path(__file__).parents[2] / "skills" / "public" / "consulting-analysis" / "SKILL.md"


class ConsultingAnalysisArtifactPolicyTests(unittest.TestCase):
    def test_html_artifacts_have_a_bounded_cece_execution_budget(self) -> None:
        content = " ".join(SKILL_PATH.read_text(encoding="utf-8-sig").split())

        for required in (
            "CECE HTML Artifact Budget",
            "single self-contained HTML file",
            "one `write_file` call",
            "one structural validation command",
            "must not use `bash`, `cat`, `tee`, heredocs, or Python to construct or rewrite the HTML",
            "Do not download new public-web material",
        ):
            with self.subTest(required=required):
                self.assertIn(required, content)


if __name__ == "__main__":
    unittest.main()
