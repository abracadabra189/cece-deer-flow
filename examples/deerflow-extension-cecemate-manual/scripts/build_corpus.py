"""Build the packaged manual without interpreting or correcting business facts.

Usage: python scripts/build_corpus.py SOURCE.md OUTPUT_DIRECTORY

Only UTF-8 input is accepted. Output has no timestamps, machine paths or raw
image URLs. Body whitespace/Markdown is retained inside each section; only
outer blank lines and explicitly audited editorial material are removed.
Heading-only nodes remain in chapter paths and in the coverage audit rather
than becoming empty search hits. Source ranges are inclusive, one-based lines.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
AUTHOR = re.compile(r"[@＠][\u3400-\u9fff]{2,8}(?=[*~\s]|$)")
OFFLINE = re.compile(r"[（(]\s*(?:已)?下线\s*[）)]")
CITATION = re.compile(r"\[\^[^\]]+\]|【[^】]*†[^】]*】")
FOOTNOTE = re.compile(r"^\s*\[\^[^\]]+\]:.*$")
HTML_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMAGE_START = re.compile(r"!\[(?:\\.|[^\]\\])*\](?:\(|\[)")

# Search vocabulary only: these never replace or supplement source claims.
ALIASES = {
    "CeCeMate": ["行业洞察", "产业数据服务平台", "CeCe"],
    "AI问数": ["智能问数", "自然语言查数"],
    "查企业": ["企业搜索", "企业查询", "企业检索"],
    "查公告": ["招标公告", "中标公告", "招中标公告"],
    "查政策": ["政策", "政策查询", "政策检索"],
    "查研报": ["研报", "研报查询", "研报检索", "研究报告"],
    "供应链图谱": ["上下游", "供应链", "上下游企业"],
    "企业监控": ["监控企业", "企业动态", "监控报告"],
    "股权穿透图": ["股权穿透", "股权关系"],
    "科技人才": ["人才检索", "人才搜索", "AI人才助手"],
    "进出口企业库": ["进口企业", "出口企业", "进出口交易"],
}


def plain_heading(value):
    """Normalize heading presentation only, never source body text."""
    value = AUTHOR.sub("", value)
    value = re.sub(r"\\([\\`*_{}\[\]()#+.!~&/\-])", r"\1", value)
    value = value.replace("**", "").replace("~~", "").replace("__", "")
    return re.sub(r"\s+", " ", value).strip()


def remove_images(value):
    """Skip balanced Markdown destinations, including parentheses in URLs."""
    count = 0
    cursor = 0
    parts = []
    while match := IMAGE_START.search(value, cursor):
        opening = value[match.end() - 1]
        closing = ")" if opening == "(" else "]"
        end = match.end()
        depth = 1
        while end < len(value) and depth:
            if value[end] == "\\":
                end += 2
                continue
            if value[end] == opening:
                depth += 1
            elif value[end] == closing:
                depth -= 1
            end += 1
        if depth:
            # Malformed markup is source content, not an omission candidate.
            parts.append(value[cursor : match.end()])
            cursor = match.end()
            continue
        parts.append(value[cursor : match.start()])
        cursor = end
        count += 1
    parts.append(value[cursor:])
    cleaned, html_count = HTML_IMAGE.subn("", "".join(parts))
    return cleaned, count + html_count


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def structured_fields(content):
    """Copy explicitly labelled blocks; never infer definitions or limitations.

    overview/entry_path are strings, features/definitions/limits are lists of
    source blocks. Numbered items retain their nested lists and tables. All
    values duplicate source evidence; content remains the authoritative body.
    """
    labels = {
        "功能概述": "overview",
        "主要功能点": "features",
        "功能定义": "definitions",
        "指标定义": "definitions",
        "定义": "definitions",
        "功能限制": "limits",
        "使用限制": "limits",
        "限制": "limits",
        "功能入口": "entry_path",
        "入口路径": "entry_path",
        "应用场景": "scenarios",
        "适用场景": "scenarios",
    }
    blocks = {key: [] for key in set(labels.values())}
    active = None
    pending = []

    def flush():
        value = "\n".join(pending).strip("\n")
        if active and value.strip():
            blocks[active].append(value)
        pending.clear()

    fenced = False
    for line in content.splitlines():
        if re.match(r"^ {0,3}(?:`{3,}|~{3,})", line):
            fenced = not fenced
        match = (
            None
            if fenced
            else re.match(
                r"^\s*(?:\d+[.、]\s*)?(?:\*\*)?(" + "|".join(labels) + r")(?:[：:]\s*(?:\*\*)?\s*(.*)|(?:\*\*)?\s*)$",
                line,
            )
        )
        if match:
            flush()
            active = labels[match[1]]
            if match[2]:
                pending.append(match[2])
        elif not fenced and re.fullmatch(r"\s*\*\*[^*]+\*\*\s*", line):
            flush()
            active = None
        elif active:
            pending.append(line)
    flush()
    result = {
        "overview": "\n\n".join(blocks["overview"]),
        "entry_path": "\n\n".join(blocks["entry_path"]),
    }
    for key in ("features", "definitions", "limits", "scenarios"):
        result[key] = []
        for block in blocks[key]:
            # Split only top-level source items, retaining nested detail verbatim.
            result[key].extend(re.split(r"\n(?=(?:\d+(?:\\?\.|、|\))|[-*])\s)", block))
    return result


def build_corpus(source_bytes):
    """Return (entries, manifest, aliases), deterministically from source bytes."""
    lines = source_bytes.decode("utf-8-sig").splitlines()
    audit = {
        "source_line_count": len(lines),
        "omitted_images": 0,
        "removed_author_annotations": 0,
        "removed_citations": 0,
        "cleaning_events": [],
        "structural_headings": [],
        "duplicate_policy": "Keep separate source occurrences; never semantically merge functions.",
        "structured_fields_policy": "Copy explicitly labelled source blocks only; absent labels stay empty. content is authoritative.",
        "policy": (
            "Business text is authoritative, including contradictions. Only images, "
            "editorial heading authors, revision authors and citation markers are "
            "removed. Retirement is inherited only from explicit offline headings."
        ),
    }
    entries = []
    stack = []
    section = None
    covered = set()
    heading_lines = []
    omitted_lines = []
    blank_lines = []
    seen_ids = Counter()
    title = ""
    revision_table = False
    revisions = []
    fence = None

    def event(kind, number, count):
        if count:
            audit[kind] += count
            audit["cleaning_events"].append({"kind": kind, "line": number, "count": count})

    def finish(end):
        if section is None:
            return
        body = section["body"]
        while body and not body[0][1].strip():
            body.pop(0)
        while body and not body[-1][1].strip():
            body.pop()
        if not body:
            if section["line"]:
                audit["structural_headings"].append(
                    {
                        "line": section["line"],
                        "chapter": section["chapter"],
                    }
                )
            return
        path = section["path"]
        entry_title = path[-1][1] if path else (title or "前言")
        chapter = section["chapter"] or entry_title
        # Full path digest protects both punctuation/slug collisions and branches.
        stem = re.sub(r"[^\w\-]+", "-", entry_title, flags=re.UNICODE).strip("-") or "section"
        digest = hashlib.sha256(json_bytes(path)).hexdigest()[:16]
        base = f"{stem}-{digest}"
        seen_ids[base] += 1
        identifier = base if seen_ids[base] == 1 else f"{base}-{seen_ids[base]}"
        alias_title = re.sub(r"^\d+(?:\.\d+)*[.、]?\s*", "", entry_title)
        alias_title = OFFLINE.sub("", alias_title).strip()
        aliases = list(dict.fromkeys([entry_title, alias_title, *ALIASES.get(alias_title, [])]))
        module = next((name for level, name in path if level == 4), None)
        module = module or next((name for level, name in path if level == 3), entry_title)
        content = "\n".join(value for _, value in body)
        structured = structured_fields(content)
        entries.append(
            {
                "id": identifier,
                "module": module,
                "title": entry_title,
                "aliases": aliases,
                **structured,
                "status": section["status"],
                "chapter": chapter,
                "content": content,
                "source_lines": [section["line"] or body[0][0], end],
            }
        )
        covered.update(number for number, value in body if value.strip())

    for number, raw in enumerate(lines, 1):
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", raw)
        in_fence = fence is not None
        if fence_match:
            marker = fence_match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        heading = None if in_fence or fence_match else HEADING.match(raw)
        if heading:
            finish(number - 1)
            level = len(heading[1])
            name = plain_heading(heading[2])
            if not title:
                title = name
            while stack and stack[-1][0] >= level:
                stack.pop()
            inherited = bool(stack and stack[-1][2])
            retired = inherited or bool(OFFLINE.search(name))
            stack.append((level, name, retired))
            path = [(depth, label) for depth, label, _ in stack]
            section = {
                "line": number,
                "path": path,
                "chapter": " / ".join(label for _, label in path),
                "status": "retired" if retired else "active",
                "body": [],
            }
            heading_lines.append(number)
            event("removed_author_annotations", number, len(AUTHOR.findall(raw)))
            revision_table = False
            continue
        if section is None:
            section = {
                "line": 0,
                "path": [],
                "chapter": "",
                "status": "active",
                "body": [],
            }
        cleaned = raw
        if not in_fence and not fence_match:
            cleaned, count = remove_images(cleaned)
            event("omitted_images", number, count)
            if FOOTNOTE.match(cleaned):
                cleaned = ""
                event("removed_citations", number, 1)
            else:
                cleaned, count = CITATION.subn("", cleaned)
                event("removed_citations", number, count)
            # This is an editorial column, not the product's author query field.
            if "|" in cleaned and "日期" in cleaned and "版本" in cleaned and "作者/修订" in cleaned:
                revision_table = True
            if revision_table and cleaned.startswith("|"):
                cells = cleaned.split("|")
                if len(cells) >= 6:
                    date = plain_heading(cells[1]).replace(" ", "")
                    version = plain_heading(cells[2]).replace(" ", "")
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and re.fullmatch(r"[Vv]?\d+(?:\.\d+)+", version):
                        revisions.append((date, version))
                    author = cells[4].strip()
                    if author and not re.fullmatch(r"[:\- ]+", author):
                        cells[4] = ""
                        cleaned = "|".join(cells)
                        event("removed_author_annotations", number, 1)
            elif cleaned.strip():
                revision_table = False
        section["body"].append((number, cleaned))
        if not raw.strip():
            blank_lines.append(number)
        elif not cleaned.strip():
            omitted_lines.append(number)
    finish(len(lines))

    accounted = covered | set(heading_lines) | set(omitted_lines) | set(blank_lines)
    unaccounted = sorted(set(range(1, len(lines) + 1)) - accounted)
    if unaccounted:
        raise ValueError(f"Unaccounted source lines: {unaccounted}")
    audit["coverage"] = {
        "retained_body_lines": sorted(covered),
        "heading_lines": heading_lines,
        "omitted_editorial_lines": omitted_lines,
        "blank_lines": blank_lines,
        "unaccounted_lines": unaccounted,
        "retained_body_line_count": len(covered),
        "retained_body_sha256": hashlib.sha256("\n".join(entry["content"] for entry in entries).encode("utf-8")).hexdigest(),
    }
    date, version = max(revisions, default=("", ""))
    manifest = {
        "title": title,
        "version": version,
        "date": date,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "entry_count": len(entries),
        "entries_sha256": hashlib.sha256(json_bytes(entries)).hexdigest(),
        "audit": audit,
    }
    return entries, manifest, ALIASES.copy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    entries, manifest, aliases = build_corpus(args.source.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, value in (
        ("entries.json", entries),
        ("manifest.json", manifest),
        ("aliases.json", aliases),
    ):
        (args.output / filename).write_bytes(json_bytes(value))
    print(
        json.dumps(
            {
                "entry_count": len(entries),
                "status_counts": dict(Counter(e["status"] for e in entries)),
                "omitted_images": manifest["audit"]["omitted_images"],
                "unaccounted_lines": manifest["audit"]["coverage"]["unaccounted_lines"],
            }
        )
    )


if __name__ == "__main__":
    main()
