"""Shared SKILL.md frontmatter parsing helpers.

The runtime parser, install-time validator, and review core all use this module
as the schema source for DeerFlow SKILL.md metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

ALLOWED_FRONTMATTER_PROPERTIES = {
    "name",
    "display_name",
    "description",
    "license",
    "allowed-tools",
    "argument-hint",
    "required-secrets",
    "secrets-autonomous",
    "metadata",
    "compatibility",
    "version",
    "author",
}

DISPLAY_NAME_MAX_LENGTH = 100


def parse_display_name(value: Any) -> str | None:
    """Validate and normalize an optional user-facing skill name.

    ``name`` remains the stable, machine-facing identifier. This field is only
    for catalog and composer presentation, so it may contain localized text.
    Keeping validation here ensures runtime loading and installation agree.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"display_name must be a string, got {type(value).__name__}")

    display_name = value.strip()
    if not display_name:
        raise ValueError("display_name cannot be empty")
    if "<" in display_name or ">" in display_name:
        raise ValueError("display_name cannot contain angle brackets (< or >)")
    if len(display_name) > DISPLAY_NAME_MAX_LENGTH:
        raise ValueError(f"display_name is too long ({len(display_name)} characters). Maximum is {DISPLAY_NAME_MAX_LENGTH} characters.")
    return display_name


# `\ufeff` is the UTF-8 byte-order mark that Windows Notepad and PowerShell's
# `Set-Content -Encoding UTF8` prepend to a saved file. It is consumed by the match, so
# neither the front matter nor the body carries it downstream.
# Delimiter whitespace must stay on its own line; do not consume body
# indentation or accept a closing line that merely starts with three hyphens.
_FRONTMATTER_RE = re.compile(r"^\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)


@dataclass(frozen=True)
class SkillMarkdownParts:
    """Parsed pieces of a SKILL.md document."""

    metadata: dict[str, Any]
    frontmatter_text: str
    body: str


def split_skill_markdown(content: str) -> tuple[SkillMarkdownParts | None, str | None]:
    """Split a SKILL.md document into frontmatter and body.

    Returns ``(parts, None)`` on success and ``(None, message)`` on failure. The
    message intentionally avoids host paths so callers can reuse it in
    deterministic review output.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None, "No YAML frontmatter found"

    frontmatter_text = match.group(1)
    try:
        metadata = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        return None, f"Invalid YAML in frontmatter: {exc}"

    if not isinstance(metadata, dict):
        return None, "Frontmatter must be a YAML dictionary"

    # YAML permits non-string keys, but downstream validation expects field
    # names to be strings.
    metadata = {str(key): value for key, value in metadata.items()}

    return (
        SkillMarkdownParts(
            metadata=metadata,
            frontmatter_text=frontmatter_text,
            body=content[match.end() :],
        ),
        None,
    )
