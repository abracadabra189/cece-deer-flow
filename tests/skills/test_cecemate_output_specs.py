"""Regression tests for the CeCeMate document and web output skills."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOC_SKILL = ROOT / "skills" / "public" / "cecemate-doc-spec"
WEB_SKILL = ROOT / "skills" / "public" / "cecemate-web-spec"


def _run(script: Path, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )


def _write_docx(
    path: Path,
    *,
    logo_location: str | None = "header",
    with_disclaimer: bool = True,
    trailing_text: str = "",
) -> None:
    disclaimer = "内容由 AI 生成，请核实重要信息" if with_disclaimer else "普通正文"
    body_drawing = '<w:drawing><a:blip r:embed="rIdLogo"/></w:drawing>' if logo_location == "body" else ""
    header_drawing = '<w:drawing><a:blip r:embed="rIdLogo"/></w:drawing>' if logo_location == "header" else ""
    body_relationships = (
        '<Relationship Id="rIdLogo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/logo.png"/>'
        if logo_location == "body"
        else ""
    )
    document = f'''<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <w:body>
        <w:p>{body_drawing}<w:r><w:t>{disclaimer}</w:t></w:r></w:p>
        <w:p><w:r><w:t>{trailing_text}</w:t></w:r></w:p>
        <w:tbl><w:tblPr><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="4800"/><w:gridCol w:w="4939"/></w:tblGrid></w:tbl>
        <w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/><w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1361" w:bottom="1361" w:left="1083" w:right="1083"/></w:sectPr>
      </w:body>
    </w:document>'''
    footer = '''<?xml version="1.0" encoding="UTF-8"?>
    <w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r></w:p>
    </w:ftr>'''
    header = f'''<?xml version="1.0" encoding="UTF-8"?>
    <w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><w:p>{header_drawing}</w:p></w:hdr>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        archive.writestr("word/header1.xml", header)
        archive.writestr("word/footer1.xml", footer)
        archive.writestr("word/_rels/document.xml.rels", f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
          <Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>{body_relationships}</Relationships>''')
        archive.writestr("word/_rels/header1.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdLogo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/logo.png"/></Relationships>')
        if logo_location:
            archive.writestr("word/media/logo.png", (DOC_SKILL / "assets" / "logo.png").read_bytes())


def test_skill_entrypoints_are_discoverable_and_chinese() -> None:
    for skill_dir, name, display_name in (
        (DOC_SKILL, "cecemate-doc-spec", "CeCeMate 文档规范"),
        (WEB_SKILL, "cecemate-web-spec", "CeCeMate 网页规范"),
    ):
        entry = skill_dir / "SKILL.md"
        content = entry.read_text(encoding="utf-8")
        assert f"name: {name}" in content
        assert f"display_name: {display_name}" in content
        assert "description:" in content
        assert "references/" in content
        assert (skill_dir / "assets" / "logo.png").is_file()


def test_web_skill_focuses_only_on_web_deliverables() -> None:
    content = (WEB_SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "cecemate-doc-spec" not in content


def test_document_checker_accepts_core_compliant_docx(tmp_path: Path) -> None:
    document = tmp_path / "compliant.docx"
    _write_docx(document)

    result = _run(DOC_SKILL / "check" / "check_doc.py", document)

    assert result.returncode == 0, result.stderr


def test_document_checker_reports_missing_required_content(tmp_path: Path) -> None:
    document = tmp_path / "missing-logo-and-disclaimer.docx"
    _write_docx(document, logo_location=None, with_disclaimer=False)

    result = _run(DOC_SKILL / "check" / "check_doc.py", document)

    assert result.returncode == 1
    assert "D-LOGO" in result.stderr
    assert "D-DISCLAIMER" in result.stderr


def test_document_checker_rejects_logo_in_body_instead_of_header(tmp_path: Path) -> None:
    document = tmp_path / "body-logo.docx"
    _write_docx(document, logo_location="body")

    result = _run(DOC_SKILL / "check" / "check_doc.py", document)

    assert result.returncode == 1
    assert "D-LOGO" in result.stderr


def test_document_checker_requires_final_single_disclaimer(tmp_path: Path) -> None:
    document = tmp_path / "misplaced-disclaimer.docx"
    _write_docx(document, trailing_text="结尾正文")

    result = _run(DOC_SKILL / "check" / "check_doc.py", document)

    assert result.returncode == 1
    assert "D-DISCLAIMER" in result.stderr


def test_web_checker_accepts_core_compliant_html(tmp_path: Path) -> None:
    page = tmp_path / "compliant.html"
    page.write_text(
        '''<!doctype html><html lang="zh-CN"><head><title>上海产业报告</title>
        <meta name="viewport" content="width=device-width, initial-scale=1"><meta name="generator" content="CeCeMate">
        <link rel="icon" href="data:image/svg+xml,%3Csvg/%3E">
        <style>:root { --blue-600:#016ADE; --gray-000:#FFFFFF; --gray-400:#E0E6EB; --gray-1200:#282B2E; --fs-body:14px; }</style>
        </head><body><header><img class="logo-mark" src="assets/logo.png" alt="行业洞察logo"></header>
        <main><section><h1>报告</h1></section><section class="disclaimer">内容由 AI 生成，请核实重要信息</section></main>
        <footer><img class="logo-mark" src="assets/logo.png" alt="行业洞察logo"></footer></body></html>''',
        encoding="utf-8",
    )

    result = _run(WEB_SKILL / "check" / "check_web.py", page)

    assert result.returncode == 0, result.stderr


def test_web_checker_reports_prohibited_or_missing_structure(tmp_path: Path) -> None:
    page = tmp_path / "invalid.html"
    page.write_text(
        '<html><head><meta name="viewport" content="width=device-width, maximum-scale=1"></head><body><main><section>正文</section></main><iframe src="x"></iframe></body></html>',
        encoding="utf-8",
    )

    result = _run(WEB_SKILL / "check" / "check_web.py", page)

    assert result.returncode == 1
    assert "W-IFRAME" in result.stderr
    assert "W-DISCLAIMER" in result.stderr
    assert "W-LOGO" in result.stderr


def test_web_checker_rejects_tokens_hidden_in_css_comments(tmp_path: Path) -> None:
    page = tmp_path / "commented-tokens.html"
    page.write_text(
        '''<html lang="zh-CN"><head><title>报告</title><meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" href="data:image/svg+xml,%3Csvg/%3E"><style>/* :root { --blue-600: x; --gray-000: x; --gray-400: x; --gray-1200: x; --fs-body: x; } */</style>
        </head><body><header><img src="assets/logo.png" alt="行业洞察logo"></header><main><section class="disclaimer">内容由 AI 生成，请核实重要信息</section></main><footer><img src="assets/logo.png" alt="行业洞察logo"></footer></body></html>''',
        encoding="utf-8",
    )

    result = _run(WEB_SKILL / "check" / "check_web.py", page)

    assert result.returncode == 1
    assert "W-TOKENS" in result.stderr


def test_web_checker_rejects_external_tracking_script(tmp_path: Path) -> None:
    page = tmp_path / "tracking.html"
    page.write_text(
        '''<html lang="zh-CN"><head><title>报告</title><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="generator" content="CeCeMate">
        <link rel="icon" href="data:image/svg+xml,%3Csvg/%3E"><style>:root { --blue-600:x; --gray-000:x; --gray-400:x; --gray-1200:x; --fs-body:x; }</style><script src="https://tracker.example/a.js"></script>
        </head><body><header><img src="assets/logo.png" alt="行业洞察logo"></header><main><section class="disclaimer">内容由 AI 生成，请核实重要信息</section></main><footer><img src="assets/logo.png" alt="行业洞察logo"></footer></body></html>''',
        encoding="utf-8",
    )

    result = _run(WEB_SKILL / "check" / "check_web.py", page)

    assert result.returncode == 1
    assert "W-EXTERNAL-SCRIPT" in result.stderr


def test_web_checker_requires_cecemate_generator(tmp_path: Path) -> None:
    page = tmp_path / "missing-generator.html"
    page.write_text(
        '''<html lang="zh-CN"><head><title>报告</title><meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" href="data:image/svg+xml,%3Csvg/%3E"><style>:root { --blue-600:x; --gray-000:x; --gray-400:x; --gray-1200:x; --fs-body:x; }</style>
        </head><body><header><img src="assets/logo.png" alt="行业洞察logo"></header><main><section class="disclaimer">内容由 AI 生成，请核实重要信息</section></main><footer><img src="assets/logo.png" alt="行业洞察logo"></footer></body></html>''',
        encoding="utf-8",
    )

    result = _run(WEB_SKILL / "check" / "check_web.py", page)

    assert result.returncode == 1
    assert "W-GENERATOR" in result.stderr
