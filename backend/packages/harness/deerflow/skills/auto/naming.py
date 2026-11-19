"""Scenario naming for auto-generated skills.

A generated skill is named ``{prefix}-{scenario-slug}`` — **stable, with no
version suffix**. Versioning lives in frontmatter ``metadata.version`` and in the
backup store's directory names, so:

- exactly one package per scenario is ever discoverable, which is what "users
  only see the latest version" requires structurally rather than by pruning;
- an update does not churn the name, so skill matching, ``skill_context``
  references and anything a user bookmarked keep working across updates;
- the name stays a valid hyphen-case skill identifier, because
  :meth:`SkillStorage.validate_skill_name` rejects anything else and the name is
  also the package directory.

The slug normally comes from the synthesis model, which sees the query and can
name the scenario meaningfully. Model output is untrusted, so it is normalized
here and, when normalization leaves nothing usable, replaced by a deterministic
hash of the query — a Chinese query therefore still yields a stable, valid,
collision-resistant slug instead of failing the synthesis or minting a new
unrelated skill on every run.

The ``-v{n}`` helpers remain for reading packages written by earlier releases,
which used a versioned visible name; :func:`parse_generated_version` and
:func:`next_skill_version` exist so the legacy sweep in
:mod:`deerflow.skills.auto.store` can recognize and retire them.
"""

from __future__ import annotations

import hashlib
import re

#: ``SkillStorage.validate_skill_name`` contract: hyphen-case, at most 64 chars.
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_SKILL_NAME_CHARS = 64

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_FALLBACK_SLUG_PREFIX = "q"
_FALLBACK_HASH_CHARS = 10


class AutoSkillNamingError(ValueError):
    """A skill name could not be built within the platform's naming contract."""


def normalize_slug(proposed: object, *, max_chars: int) -> str:
    """Normalize an untrusted proposed slug, returning ``""`` when unusable.

    Lowercases, collapses every run of non-alphanumeric characters into a single
    hyphen, and trims leading/trailing hyphens so the result already satisfies
    the hyphen-case pattern before length fitting.
    """
    if not isinstance(proposed, str):
        return ""
    collapsed = _NON_SLUG_CHARS.sub("-", proposed.strip().lower())
    slug = collapsed.strip("-")
    if not slug:
        return ""
    return _fit_slug(slug, max_chars)


def _fit_slug(slug: str, max_chars: int) -> str:
    """Truncate ``slug`` to ``max_chars`` without leaving a trailing hyphen."""
    if max_chars <= 0:
        return ""
    if len(slug) <= max_chars:
        return slug
    return slug[:max_chars].rstrip("-")


def deterministic_slug(query: str) -> str:
    """Return a stable slug derived from the query itself.

    Used when the model's proposal normalizes to nothing (for example a purely
    CJK scenario name). Normalization strips surrounding whitespace and
    casefolds, so trivially different phrasings of one question map to one
    scenario series.
    """
    normalized = " ".join(query.split()).casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:_FALLBACK_HASH_CHARS]
    return f"{_FALLBACK_SLUG_PREFIX}{digest}"


def scenario_slug(proposed: object, *, query: str, max_chars: int = 48) -> str:
    """Resolve the scenario slug for a generated skill name.

    Prefers the model's normalized proposal; falls back to the deterministic
    query hash so naming never fails the synthesis.
    """
    slug = normalize_slug(proposed, max_chars=max_chars)
    if slug:
        return slug
    return _fit_slug(deterministic_slug(query), max_chars)


def normalize_prefix(prefix: object) -> str:
    """Normalize the configured name prefix, raising when it cannot form a name."""
    normalized = normalize_slug(prefix, max_chars=MAX_SKILL_NAME_CHARS)
    if not normalized:
        raise AutoSkillNamingError(f"auto_skill.name_prefix is not a usable slug: {prefix!r}")
    return normalized


def resolve_skill_name(*, prefix: str, slug: str) -> str:
    """Build and validate the stable visible name ``{prefix}-{slug}``.

    The slug absorbs any overflow so the whole name stays within
    :data:`MAX_SKILL_NAME_CHARS`; raises :class:`AutoSkillNamingError` when no
    valid name fits.
    """
    normalized_prefix = normalize_prefix(prefix)
    if not slug:
        raise AutoSkillNamingError("a scenario slug is required")

    slug_budget = MAX_SKILL_NAME_CHARS - len(normalized_prefix) - 1
    fitted_slug = _fit_slug(slug, slug_budget).rstrip("-")
    if not fitted_slug:
        raise AutoSkillNamingError(f"no room for a scenario slug in {MAX_SKILL_NAME_CHARS} chars (prefix={normalized_prefix!r})")

    name = f"{normalized_prefix}-{fitted_slug}"
    if not SKILL_NAME_PATTERN.fullmatch(name):
        raise AutoSkillNamingError(f"generated skill name is not hyphen-case: {name!r}")
    return name


# ── legacy versioned names (earlier releases) ────────────────────────────────


def version_pattern(*, prefix: str, slug: str) -> re.Pattern[str]:
    """Compiled matcher for one scenario's legacy versioned series."""
    return re.compile(rf"^{re.escape(prefix)}-{re.escape(slug)}-v(\d+)$")


def parse_generated_version(name: object, *, prefix: str, slug: str) -> int | None:
    """Return the version of a legacy versioned name in this series, else ``None``."""
    if not isinstance(name, str):
        return None
    match = version_pattern(prefix=prefix, slug=slug).match(name)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def next_skill_version(existing_names: object, *, prefix: str, slug: str) -> int:
    """Return the next legacy version number for a scenario, starting at 1.

    Retained for reading packages written before the stable-name scheme; new
    writes take their version from :func:`deerflow.skills.auto.store.write_skill`.
    """
    highest = 0
    if isinstance(existing_names, (list, tuple, set, frozenset)):
        for name in existing_names:
            version = parse_generated_version(name, prefix=prefix, slug=slug)
            if version is not None and version > highest:
                highest = version
    return highest + 1
