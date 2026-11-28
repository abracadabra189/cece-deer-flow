"""Shared SKILL.md frontmatter parsing helpers.

The runtime parser, install-time validator, and review core all use this module
as the schema source for DeerFlow SKILL.md metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator


class ReferenceCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    title: str
    preview_image_path: str
    artifact_name: str | None = None
    artifact_path: str | None = None

    @field_validator("title", "preview_image_path")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class StarterReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    id: str | None = None
    name: str
    path: str

    @field_validator("name", "path")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class SkillCatalogMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    catalog_category: Literal["business_scenario", "general_tool"] | None = None
    reference_cases: list[ReferenceCase] = []
    starter_prompt: str | None = None
    starter_references: list[StarterReference] = []

    @field_validator("starter_prompt")
    @classmethod
    def normalize_prompt(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


def parse_catalog_metadata(metadata: dict[str, Any]) -> SkillCatalogMetadata:
    return SkillCatalogMetadata.model_validate({key: metadata[key] for key in SkillCatalogMetadata.model_fields if key in metadata})


ALLOWED_FRONTMATTER_PROPERTIES = {
    "name",
    "display_name",
    "display_description",
    "icon_path",
    "example_queries",
    "catalog_category",
    "reference_cases",
    "starter_prompt",
    "starter_references",
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
EXAMPLE_QUERIES_MAX_COUNT = 3


def parse_optional_display_text(value: Any, field_name: str) -> str | None:
    """Normalize optional presentation strings without coercing YAML values."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value.strip() or None


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


def parse_example_queries(value: Any) -> tuple[str, ...]:
    """Validate optional user-facing example prompts for a skill card."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("example_queries must be a list of strings")
    if len(value) > EXAMPLE_QUERIES_MAX_COUNT:
        raise ValueError(f"example_queries cannot contain more than {EXAMPLE_QUERIES_MAX_COUNT} items")

    queries: list[str] = []
    for query in value:
        if not isinstance(query, str):
            raise ValueError("example_queries must contain only strings")
        normalized = query.strip()
        if not normalized:
            raise ValueError("example_queries cannot contain empty strings")
        queries.append(normalized)
    return tuple(queries)


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
