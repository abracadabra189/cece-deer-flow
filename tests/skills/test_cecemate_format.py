"""Regression tests for the CeCeMate format skill (JSON -> HTML/DOCX)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "public" / "cecemate-format"
CONFIG = SKILL / "brand-config.json"
LOGO = SKILL / "assets" / "logo.png"
TEMPLATE = SKILL / "templates" / "doc.docx"
ONE_PIXEL_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


def _run(script: Path, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *(str(arg) for arg in args)],
        text=True,
        capture_output=True,
        check=False,
    )


def _copy_zip(source: Path, target: Path, replacements: dict[str, bytes]) -> None:
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, replacements.get(info.filename, src.read(info.filename)))


def test_brand_config_and_logo_hash_match() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["assets"]["logo"]["sha256"] == hashlib.sha256(LOGO.read_bytes()).hexdigest()
    assert config["assets"]["logo"]["width"] == 2529
    assert config["assets"]["logo"]["height"] == 480


def test_skill_entrypoint_is_discoverable() -> None:
    content = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "name: cecemate-format" in content
    assert "display_name: CeCeMate 格式交付" in content
    assert "references/content-schema.md" in content


def test_doc_template_passes_required_check() -> None:
    result = _run(
        SKILL / "scripts" / "check_doc_required.py",
        TEMPLATE,
        "--allow-placeholders",
    )
    assert result.returncode == 0, result.stderr
    assert "通过" in result.stdout


def test_doc_cover_has_no_header_and_header_name_is_right_aligned() -> None:
    pytest.importorskip("docx")
    from docx import Document
    from docx.enum.text import WD_TAB_ALIGNMENT

    document = Document(TEMPLATE)
    cover_header = "".join(paragraph.text for paragraph in document.sections[0].header.paragraphs)
    assert cover_header.strip() == ""

    header = document.sections[1].header.paragraphs[0]
    assert "{{DOC_NAME}}" in header.text
    assert any(tab.alignment == WD_TAB_ALIGNMENT.RIGHT and abs(tab.position.cm - 17.18) < 0.05 for tab in header.paragraph_format.tab_stops)


def test_doc_checker_rejects_missing_disclaimer(tmp_path: Path) -> None:
    target = tmp_path / "missing-disclaimer.docx"
    with zipfile.ZipFile(TEMPLATE) as archive:
        document = archive.read("word/document.xml")
    document = document.replace("内容由 AI 生成，请核实重要信息".encode(), "普通正文".encode())
    _copy_zip(TEMPLATE, target, {"word/document.xml": document})

    result = _run(SKILL / "scripts" / "check_doc_required.py", target)
    assert result.returncode == 1
    assert "D-DISCLAIMER" in result.stderr


def test_doc_checker_ignores_non_logo_layout_issues(tmp_path: Path) -> None:
    target = tmp_path / "bad-layout.docx"
    with zipfile.ZipFile(TEMPLATE) as archive:
        document = archive.read("word/document.xml")
    document = document.replace(b'w:top="1361"', b'w:top="567"')
    document = document.replace(b'w:left="1083"', b'w:left="567"')
    _copy_zip(TEMPLATE, target, {"word/document.xml": document})

    result = _run(
        SKILL / "scripts" / "check_doc_required.py",
        target,
        "--allow-placeholders",
    )
    assert result.returncode == 0, result.stderr


def test_doc_checker_rejects_blank_page_from_consecutive_breaks(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    from docx import Document

    document = Document(TEMPLATE)
    placeholder = next(p for p in document.paragraphs if "{{CONTENT_PLACEHOLDER}}" in p.text)
    page_break = document.add_page_break()
    placeholder._p.addprevious(page_break._p)
    target = tmp_path / "blank-page.docx"
    document.save(target)

    result = _run(
        SKILL / "scripts" / "check_doc_required.py",
        target,
        "--allow-placeholders",
    )
    assert result.returncode == 1
    assert "D-BLANK-PAGE" in result.stderr


def test_doc_checker_rejects_stretched_logo(tmp_path: Path) -> None:
    target = tmp_path / "stretched-logo.docx"
    with zipfile.ZipFile(TEMPLATE) as archive:
        document = archive.read("word/document.xml")
    document = document.replace(b'cx="2086425"', b'cx="300000"', 1)
    _copy_zip(TEMPLATE, target, {"word/document.xml": document})

    result = _run(
        SKILL / "scripts" / "check_doc_required.py",
        target,
        "--allow-placeholders",
    )
    assert result.returncode == 1
    assert "D-LOGO-ASPECT" in result.stderr


def test_doc_checker_rejects_external_image(tmp_path: Path) -> None:
    target = tmp_path / "external-image.docx"
    with zipfile.ZipFile(TEMPLATE) as archive:
        rels = archive.read("word/_rels/document.xml.rels")
    rels = rels.replace(
        b"</Relationships>",
        b'<Relationship Id="rIdExt" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.com/x.png" TargetMode="External"/></Relationships>',
    )
    _copy_zip(TEMPLATE, target, {"word/_rels/document.xml.rels": rels})

    result = _run(
        SKILL / "scripts" / "check_doc_required.py",
        target,
        "--allow-placeholders",
    )
    assert result.returncode == 1
    assert "D-EXTERNAL" in result.stderr


def test_doc_checker_rejects_tampered_logo(tmp_path: Path) -> None:
    target = tmp_path / "tampered-logo.docx"
    with zipfile.ZipFile(TEMPLATE) as archive:
        names = [name for name in archive.namelist() if name.startswith("word/media/")]
    _copy_zip(TEMPLATE, target, {name: ONE_PIXEL_PNG for name in names})

    result = _run(SKILL / "scripts" / "check_doc_required.py", target)
    assert result.returncode == 1
    assert "D-LOGO" in result.stderr


def _content_payload() -> dict:
    return {
        "meta": {
            "title": "行业洞察人工智能企业风险研究报告",
            "date": "2026-11-18",
            "period": "2026-10-20 至 2026-11-12",
            "scope": "企业风险数据",
            "author": "CeCeMate 自动生成",
        },
        "blocks": [
            {"type": "heading", "level": 1, "text": "整体表现"},
            {"type": "paragraph", "text": "正文段落。"},
            {
                "type": "table",
                "caption": "表 1　经济核心指标情况",
                "source": "数据来源：行业洞察中台",
                "columns": [
                    {"label": "指标", "align": "left", "width_cm": 8},
                    {"label": "本期", "align": "right", "width_cm": 9},
                ],
                "rows": [["融资额（万元）", "18,426.6"]],
            },
            {
                "type": "data_note",
                "source": "测试数据",
                "scope": "全量",
                "period": "2026 年",
                "limitations": ["样本有限"],
            },
        ],
    }


def test_output_names_follow_title(tmp_path: Path) -> None:
    payload = _content_payload()
    payload["meta"]["title"] = "我的报告"
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"

    pytest.importorskip("docx")
    docx = _run(SKILL / "scripts" / "render_docx.py", content, "--out", out)
    assert docx.returncode == 0, docx.stderr
    assert (out / "我的报告.docx").is_file()


def test_render_defaults_to_docx_only(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    payload = _content_payload()
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"

    result = _run(SKILL / "scripts" / "render.py", content, "--out", out)
    assert result.returncode == 0, result.stderr
    assert (out / "行业洞察人工智能企业风险研究报告.docx").is_file()
    assert not (out / "行业洞察人工智能企业风险研究报告.html").exists()
    assert not (out / "行业洞察人工智能企业风险研究报告.pdf").exists()


def test_render_orchestrator_rejects_html_format(tmp_path: Path) -> None:
    payload = _content_payload()
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"

    web = _run(SKILL / "scripts" / "render.py", content, "--out", out, "--formats", "html")
    assert web.returncode == 1
    assert "html" in web.stderr.lower()
    assert not (out / "行业洞察人工智能企业风险研究报告.html").exists()


def test_web_responsive_css(tmp_path: Path) -> None:
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "content_blocks.py", content, "--out", out).returncode == 0
    html = (out / "行业洞察人工智能企业风险研究报告.html").read_text(encoding="utf-8")
    assert "@media (max-width: 480px)" in html
    assert "min-width: 680px" in html
    assert "overflow-x: auto" in html
    assert "flex-wrap: wrap" in html


def test_web_preflight_allows_pages_without_data_note(tmp_path: Path) -> None:
    payload = _content_payload()
    payload["blocks"] = [block for block in payload["blocks"] if block.get("type") != "data_note"]
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _run(SKILL / "scripts" / "content_blocks.py", content, "--out", tmp_path / "out")
    assert result.returncode == 0, result.stderr


def test_web_preflight_allows_a_single_metric_when_the_content_calls_for_it(tmp_path: Path) -> None:
    payload = _content_payload()
    payload["blocks"].insert(1, {"type": "metrics", "items": [{"label": "唯一指标", "value": "1"}]})
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _run(SKILL / "scripts" / "content_blocks.py", content, "--out", tmp_path / "out")
    assert result.returncode == 0, result.stderr


def test_web_modules_render(tmp_path: Path) -> None:
    shutil.copyfile(SKILL / "examples" / "figures" / "chart.svg", tmp_path / "chart.svg")
    payload = {
        "meta": {"title": "Web 组件测试", "date": "2026-11-24"},
        "blocks": [
            {
                "type": "hero",
                "title": "产业风险简报",
                "lead": "一句话导语。",
                "chips": ["报告编号：A-1", "更新时间：2026-11-24", "口径：测试"],
                "tags": [{"text": "信息", "tone": "info"}],
            },
            {
                "type": "metrics",
                "items": [
                    {"label": "成交额", "value": "18,426", "unit": "万元", "change": "↑ 23.8%", "tone": "success"},
                    {"label": "退款率", "value": "3.6", "unit": "%", "change": "↓ 0.9pct", "tone": "danger"},
                ],
            },
            {
                "type": "chart_row",
                "primary": {"src": "chart.svg", "caption": "图 1　趋势", "source": "来源：测试"},
                "secondary": {"src": "chart.svg", "caption": "图 2　结构", "source": "来源：测试"},
            },
            {
                "type": "conclusion",
                "title": "综合研判",
                "paragraphs": ["判断正文。"],
                "findings": ["发现一", "发现二", "发现三"],
            },
            {
                "type": "matrix",
                "items": [
                    {"title": "主体 A", "status": "风险", "tone": "danger", "text": "说明。"},
                    {"title": "主体 B", "status": "关注", "tone": "warning", "text": "说明。"},
                    {"title": "主体 C", "status": "达标", "tone": "success", "text": "说明。"},
                    {"title": "主体 D", "status": "待办", "tone": "todo", "text": "说明。"},
                ],
            },
            {
                "type": "timeline",
                "items": [
                    {"date": "2026-11-21", "title": "事件一", "text": "说明。"},
                    {"date": "2026-11-22", "title": "事件二", "text": "说明。"},
                    {"date": "2026-11-23", "title": "事件三", "text": "说明。"},
                    {"date": "2026-11-24", "title": "事件四", "text": "说明。"},
                ],
            },
            {"type": "data_note", "source": "测试数据", "scope": "全量", "period": "2026 年", "limitations": ["样本有限"]},
            {"type": "callout", "tone": "warning", "text": "需要复核。"},
            {"type": "actions", "items": [{"label": "下载", "href": "#", "variant": "primary"}]},
        ],
    }
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = _run(SKILL / "scripts" / "content_blocks.py", content, "--out", tmp_path / "out")
    assert result.returncode == 0, result.stderr
    html = (tmp_path / "out" / "Web 组件测试.html").read_text(encoding="utf-8")
    for class_name in ("hero", "metrics", "chart-row", "conclusion-grid", "matrix-grid", "timeline", "data-note", "callout-warning", "actions"):
        assert class_name in html


def test_web_toc_renders_anchor_links(tmp_path: Path) -> None:
    payload = _content_payload()
    payload["blocks"].insert(0, {"type": "toc", "title": "目录"})
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = _run(SKILL / "scripts" / "content_blocks.py", content, "--out", tmp_path / "out")
    assert result.returncode == 0, result.stderr
    html = (tmp_path / "out" / "行业洞察人工智能企业风险研究报告.html").read_text(encoding="utf-8")
    assert '<nav class="toc"' in html
    assert 'href="#sec-1"' in html
    assert "整体表现" in html


def test_web_checker_rejects_missing_footer_logo(tmp_path: Path) -> None:
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "content_blocks.py", content, "--out", out).returncode == 0
    page = out / "行业洞察人工智能企业风险研究报告.html"
    html = page.read_text(encoding="utf-8")
    html = re.sub(r'<img class="footer-logo"[^>]*>', "", html)
    page.write_text(html, encoding="utf-8")

    result = _run(SKILL / "scripts" / "check_web_required.py", page)
    assert result.returncode == 1
    assert "W-LOGO" in result.stderr


def test_web_checker_ignores_non_logo_disclaimer_issues(tmp_path: Path) -> None:
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "content_blocks.py", content, "--out", out).returncode == 0
    page = out / "行业洞察人工智能企业风险研究报告.html"
    html = page.read_text(encoding="utf-8")
    html = html.replace("</head>", '<meta name="viewport" content="maximum-scale=1"></head>')
    page.write_text(html, encoding="utf-8")

    result = _run(SKILL / "scripts" / "check_web_required.py", page)
    assert result.returncode == 0, result.stderr


def test_web_checker_does_not_make_external_resources_or_placeholders_hard_failures(tmp_path: Path) -> None:
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "content_blocks.py", content, "--out", out).returncode == 0
    page = out / "行业洞察人工智能企业风险研究报告.html"
    html = page.read_text(encoding="utf-8")
    html = html.replace("</body>", '<iframe src="https://example.com/x"></iframe>{{TITLE}}</body>')
    page.write_text(html, encoding="utf-8")

    result = _run(SKILL / "scripts" / "check_web_required.py", page)
    assert result.returncode == 0, result.stderr


def test_web_checker_does_not_reject_disclaimer_text_repeated_in_footer(tmp_path: Path) -> None:
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "content_blocks.py", content, "--out", out).returncode == 0
    page = out / "行业洞察人工智能企业风险研究报告.html"
    html = page.read_text(encoding="utf-8")
    html = html.replace("</footer>", "<span>内容由 AI 生成，请核实重要信息</span></footer>")
    page.write_text(html, encoding="utf-8")

    result = _run(SKILL / "scripts" / "check_web_required.py", page)
    assert result.returncode == 0, result.stderr


def test_web_checker_reports_missing_brand_requirements_for_non_utf8_html(tmp_path: Path) -> None:
    page = tmp_path / "broken.html"
    page.write_bytes(b"\xff\xfe")

    result = _run(SKILL / "scripts" / "check_web_required.py", page)
    assert result.returncode == 1
    assert "W-PACKAGE" not in result.stderr
    assert "W-LOGO" in result.stderr
    assert "W-DISCLAIMER" in result.stderr


def test_web_checker_rejects_tampered_logo(tmp_path: Path) -> None:
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "content_blocks.py", content, "--out", out).returncode == 0
    page = out / "行业洞察人工智能企业风险研究报告.html"
    html = page.read_text(encoding="utf-8")
    replacement = "data:image/png;base64," + base64.b64encode(ONE_PIXEL_PNG).decode("ascii")
    html = re.sub(r'src="data:image/png;base64,[^"]+"', f'src="{replacement}"', html)
    page.write_text(html, encoding="utf-8")

    result = _run(SKILL / "scripts" / "check_web_required.py", page)
    assert result.returncode == 1
    assert "W-LOGO-HASH" in result.stderr


def test_docx_renderer_requires_table_widths(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    payload = _content_payload()
    for column in payload["blocks"][2]["columns"]:
        column.pop("width_cm", None)
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = _run(SKILL / "scripts" / "render_docx.py", content, "--out", tmp_path / "out")
    assert result.returncode == 1
    assert "width_cm" in result.stderr


def test_docx_without_toc_removes_template_toc_page(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "render_docx.py", content, "--out", out).returncode == 0
    with zipfile.ZipFile(out / "行业洞察人工智能企业风险研究报告.docx") as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert "TOC \\o" not in document


def test_docx_h1_adds_page_break(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    from docx import Document
    from docx.oxml.ns import qn

    content = tmp_path / "content.json"
    content.write_text(
        json.dumps(
            {
                "meta": {"title": "分页测试", "date": "2026-11-24"},
                "blocks": [
                    {"type": "heading", "level": 1, "text": "摘要", "numbered": False},
                    {"type": "paragraph", "text": "摘要。"},
                    {"type": "heading", "level": 1, "text": "第一章"},
                    {"type": "paragraph", "text": "正文。"},
                    {"type": "heading", "level": 1, "text": "第二章"},
                    {"type": "paragraph", "text": "正文。"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert _run(SKILL / "scripts" / "render_docx.py", content, "--out", out).returncode == 0

    document = Document(out / "分页测试.docx")
    page_breaks = sum(1 for paragraph in document.paragraphs if any(br.attrib.get(qn("w:type")) == "page" for br in paragraph._p.findall(f".//{qn('w:br')}")))
    assert page_breaks >= 2


def test_docx_unnumbered_heading_does_not_consume_chapter_number(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    content = tmp_path / "content.json"
    content.write_text(
        json.dumps(
            {
                "meta": {"title": "测试报告", "date": "2026-11-18"},
                "blocks": [
                    {"type": "heading", "level": 1, "text": "摘要", "numbered": False},
                    {"type": "paragraph", "text": "摘要正文。"},
                    {"type": "heading", "level": 1, "text": "整体表现"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    result = _run(SKILL / "scripts" / "render_docx.py", content, "--out", out)
    assert result.returncode == 0, result.stderr

    from docx import Document

    texts = [paragraph.text for paragraph in Document(out / "测试报告.docx").paragraphs]
    assert "摘要" in texts
    assert "一、整体表现" in texts


def test_docx_renderer_round_trip(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    pytest.importorskip("fitz")
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "docout"

    result = _run(SKILL / "scripts" / "render_docx.py", content, "--out", out)
    assert result.returncode == 0, result.stderr
    document = out / "行业洞察人工智能企业风险研究报告.docx"
    assert document.is_file()
    from docx import Document

    texts = [paragraph.text for paragraph in Document(document).paragraphs]
    assert "一、整体表现" in texts
    assert not any("{{CONTENT_PLACEHOLDER}}" in text for text in texts)

    check = _run(SKILL / "scripts" / "check_doc_required.py", document)
    assert check.returncode == 0, check.stderr


def test_docx_toc_uses_static_entries(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    payload = _content_payload()
    payload["blocks"].insert(0, {"type": "toc", "title": "目录"})
    content = tmp_path / "content.json"
    content.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"

    result = _run(SKILL / "scripts" / "render_docx.py", content, "--out", out)
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(out / "行业洞察人工智能企业风险研究报告.docx") as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        settings = archive.read("word/settings.xml").decode("utf-8")
    assert "PAGEREF" in document
    assert "TOC \\o" not in document
    assert "右键更新目录" not in document
    assert "updateFields" in settings


def test_pdf_renderer_round_trip(tmp_path: Path) -> None:
    pytest.importorskip("weasyprint")
    pytest.importorskip("fitz")
    content = tmp_path / "content.json"
    content.write_text(json.dumps(_content_payload(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "pdfout"

    result = _run(SKILL / "scripts" / "render_pdf.py", content, "--out", out)
    assert result.returncode == 0, result.stderr
    pdf = out / "行业洞察人工智能企业风险研究报告.pdf"
    assert pdf.is_file()

    check = _run(SKILL / "scripts" / "check_pdf_required.py", pdf)
    assert check.returncode == 0, check.stderr
