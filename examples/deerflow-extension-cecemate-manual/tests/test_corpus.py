"""Corpus contract and lossless manual conversion regressions (no source required)."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_corpus.py"
DATA = ROOT / "deerflow_extension_cecemate_manual" / "data"


def builder():
    spec = importlib.util.spec_from_file_location("build_corpus", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preserves_intro_tables_lists_contradictions_and_source_ranges():
    source = "\n".join(
        [
            "# 手册",
            "介绍不能丢失。",
            "### 功能介绍",
            "模块简介。",
            "#### 企业",
            "##### 查企业@某作者",
            "支持十条。",
            "|字段|限制|",
            "|---|---|",
            "|公告、舆情|不限条数|",
            "1. 列表",
            "    - 嵌套详情",
            "##### 空结构",
            "###### 子项",
            "保留全部。",
        ]
    )
    entries, manifest, _ = builder().build_corpus(source.encode())
    assert [e["title"] for e in entries] == ["手册", "功能介绍", "查企业", "子项"]
    entry = entries[2]
    assert entry["content"] == "\n".join(source.splitlines()[6:12])
    assert entry["source_lines"] == [6, 12]
    assert entry["module"] == "企业"
    assert "企业 / 空结构 / 子项" in entries[3]["chapter"]
    assert manifest["audit"]["coverage"]["unaccounted_lines"] == []


def test_retirement_is_explicit_and_inherited_never_keyword_wide():
    source = """# 手册
### 功能介绍
#### 资讯
##### ~~舆情（下线）~~
旧内容。
###### 子功能
继续保留。
##### 公告（下线）
旧公告。
#### 供应链
##### 查公告
查询公告及企业舆情。不是下线功能。
##### ~~普通删除线~~
仍然有效。
"""
    entries, _, _ = builder().build_corpus(source.encode())
    assert [e["status"] for e in entries] == ["retired"] * 3 + ["active"] * 2
    assert "公告及企业舆情" in entries[3]["content"]


def test_cleaning_removes_only_editorial_material_and_audits_it():
    source = """# 手册
#### 企业@某作者
正文 ![截图](https://example.test/a_(b).png) 保留。[^1]
<img src="private.png" alt="图" />
[^1]: 内部引用说明
作者、专利引用次数、公告、舆情都是业务字段。
```text
# 这不是标题
```
"""
    entries, manifest, _ = builder().build_corpus(source.encode())
    assert len(entries) == 1
    assert entries[0]["content"] == ("正文  保留。\n\n\n作者、专利引用次数、公告、舆情都是业务字段。\n```text\n# 这不是标题\n```")
    audit = manifest["audit"]
    assert audit["omitted_images"] == 2
    assert audit["removed_author_annotations"] == 1
    assert audit["removed_citations"] == 2


def test_ids_are_heading_based_unique_and_deterministic():
    build = builder().build_corpus
    source = b"# Manual\n#### A\n##### Same\none\n##### Same\ntwo\n#### B\n##### Same\nthree\n"
    entries, manifest, aliases = build(source)
    changed, _, _ = build(source.replace(b"one", b"changed body"))
    assert len({e["id"] for e in entries}) == 3
    assert [e["id"] for e in entries] == [e["id"] for e in changed]
    assert (entries, manifest, aliases) == build(source)


def test_structured_fields_require_explicit_labels_and_keep_nested_details():
    source = """# 手册
#### 功能
**功能概述：**源文概述。
概述第二行。
**主要功能点：**
1. 查询。
    - 保留嵌套。
2. 导出。
**指标定义：**指标等于原文口径。
**使用限制：**最多十条。
**入口路径：**首页 > 查询。
**应用场景：**
银行拓客。
#### 未标注
这段文字提到限制但不是明确标签。[1] [2](https://example.test) [3][ref]
[ref]: https://example.test
"""
    entries, _, _ = builder().build_corpus(source.encode())
    entry, unlabelled = entries
    assert entry["overview"] == "源文概述。\n概述第二行。"
    assert entry["features"] == ["1. 查询。\n    - 保留嵌套。", "2. 导出。"]
    assert entry["definitions"] == ["指标等于原文口径。"]
    assert entry["limits"] == ["最多十条。"]
    assert entry["entry_path"] == "首页 > 查询。"
    assert entry["scenarios"] == ["银行拓客。"]
    for key in ("overview", "entry_path", "features", "definitions", "limits"):
        assert not unlabelled[key]
    assert "[1] [2](https://example.test) [3][ref]" in unlabelled["content"]
    assert "[ref]: https://example.test" in unlabelled["content"]


def test_revision_metadata_and_author_column_cleanup():
    source = """# 产品手册
**文档修改记录**
|**日期**|**版本**|**描述**|**作者/修订**|
|---|---|---|---|
|**2024\\-12\\-20**|**V1\\.0**|首次|全员|
|**2025\\-0****9****\\-1****1**|**V1\\.****1**|更新|某作者|
#### 功能
正文。
"""
    entries, manifest, _ = builder().build_corpus(source.encode())
    assert manifest["version"] == "V1.1"
    assert manifest["date"] == "2025-09-11"
    assert "全员" not in entries[0]["content"]
    assert "某作者" not in entries[0]["content"]
    assert "首次" in entries[0]["content"]
    assert manifest["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()


def test_cli_is_byte_reproducible(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# 手册\n#### 功能\n完整内容。\n", encoding="utf-8")
    output = tmp_path / "data"
    command = [sys.executable, str(SCRIPT), str(source), str(output)]
    subprocess.run(command, check=True, capture_output=True)
    first = {p.name: p.read_bytes() for p in output.iterdir()}
    subprocess.run(command, check=True, capture_output=True)
    assert first == {p.name: p.read_bytes() for p in output.iterdir()}


def test_packaged_corpus_contract_and_audit():
    entries = json.loads((DATA / "entries.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    aliases = json.loads((DATA / "aliases.json").read_text(encoding="utf-8"))
    assert len(entries) == manifest["entry_count"] > 100
    assert len({e["id"] for e in entries}) == len(entries)
    for entry in entries:
        assert set(entry) == {
            "id",
            "module",
            "title",
            "aliases",
            "scenarios",
            "status",
            "chapter",
            "content",
            "source_lines",
            "overview",
            "features",
            "definitions",
            "limits",
            "entry_path",
        }
        assert entry["content"].strip()
        assert isinstance(entry["chapter"], str)
        assert all(isinstance(entry[k], str) for k in ("overview", "entry_path"))
        assert all(isinstance(entry[k], list) for k in ("features", "definitions", "limits"))
        assert entry["status"] in {"active", "retired"}
        assert all(isinstance(entry[k], list) for k in ("aliases", "scenarios", "source_lines"))
        assert 1 <= entry["source_lines"][0] <= entry["source_lines"][1]
        assert "![Image]" not in entry["content"]
    retired = {e["title"] for e in entries if e["status"] == "retired"}
    assert retired == {
        "企业分群（下线）",
        "项目库（下线）",
        "舆情（下线）",
        "公告（下线）",
        "法律法规（下线）",
    }
    assert any(e["title"] == "查公告" and e["status"] == "active" for e in entries)
    assert any(e["title"] == "企业舆情" and e["status"] == "active" for e in entries)
    assert manifest["audit"]["omitted_images"] == 216
    assert manifest["audit"]["coverage"]["unaccounted_lines"] == []
    assert hashlib.sha256((DATA / "entries.json").read_bytes()).hexdigest() == manifest["entries_sha256"]
    assert all(isinstance(k, str) and isinstance(v, list) for k, v in aliases.items())
