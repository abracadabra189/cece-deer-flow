"""Keep a generated skill abstract: concrete entities belong to examples only.

A package published to the global store is matched by *every* later run of the
same scenario class, so a body that hard-codes one company's name stops
describing a method and starts describing one answer. Requirement: the reasoning
flow, the data-fetch path and the answer format are abstracted to a *class* of
questions; the run's concrete subject may appear only inside the examples
section.

The prompt asks for that, but a prompt is a request, not a guarantee, and the
output is shared with every user. This module is the deterministic half:

- :func:`collect_entities` normalizes the entity list the synthesis model
  declares for the run (proper nouns, codes, and the specific dates/amounts it
  used);
- :func:`find_leaked_entities` reports which of them appear in a surface that
  must stay abstract;
- :func:`redact_entities` replaces them with :data:`ENTITY_PLACEHOLDER`, longest
  entity first so a short one cannot split a longer match.

The caller (:mod:`deerflow.skills.auto.synthesizer`) gives the model one repair
attempt before falling back to redaction, so a leaking skill is never published
and a recoverable leak does not discard the whole trajectory.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)

#: Replaces a concrete entity that leaked into a surface that must stay abstract.
ENTITY_PLACEHOLDER = "【实体】"
#: One- or two-character strings are too ambiguous to match on ("A", "3", "24").
MIN_ENTITY_CHARS = 2
#: Anything longer is a sentence, not an entity; redacting it would gut the text.
MAX_ENTITY_CHARS = 64
#: Bound on how many entities one payload may declare.
MAX_ENTITIES = 40
#: Separators accepted when a model returns one string instead of a list.
_ENTITY_SPLIT_RE = re.compile(r"[,，;；、\n\r\t]+")
#: Consecutive placeholders collapse into one so redaction stays readable.
_PLACEHOLDER_RUN_RE = re.compile(rf"(?:{re.escape(ENTITY_PLACEHOLDER)}\s*){{2,}}")


def _candidate_tokens(raw: object) -> list[str]:
    """Flatten a model-declared entity value into candidate strings."""
    if isinstance(raw, str):
        return [part.strip() for part in _ENTITY_SPLIT_RE.split(raw)]
    if isinstance(raw, (list, tuple, set, frozenset)):
        tokens: list[str] = []
        for item in raw:
            if isinstance(item, str):
                tokens.append(item.strip())
        return tokens
    return []


def collect_entities(raw: object) -> tuple[str, ...]:
    """Normalize the entity list declared for one run.

    Model output is untrusted: non-strings are dropped, entries are stripped and
    length-bounded, duplicates are removed case-insensitively (the first spelling
    wins, because that is the one the body text uses), and the total is capped so
    a model that declares the whole answer as "entities" cannot turn redaction
    into a wipe of the published skill.
    """
    entities: list[str] = []
    seen: set[str] = set()
    for token in _candidate_tokens(raw):
        if not (MIN_ENTITY_CHARS <= len(token) <= MAX_ENTITY_CHARS):
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        entities.append(token)
        if len(entities) >= MAX_ENTITIES:
            break
    return tuple(entities)


def find_leaked_entities(text: str, entities: Iterable[str]) -> tuple[str, ...]:
    """Return the entities that appear in ``text``, in declaration order.

    Comparison is case-insensitive: a generated body may capitalize a ticker or a
    brand differently from the trajectory that produced it, and the abstraction
    rule does not depend on spelling.
    """
    if not isinstance(text, str) or not text:
        return ()
    haystack = text.casefold()
    return tuple(entity for entity in entities if entity and entity.casefold() in haystack)


def redact_entities(text: str, entities: Iterable[str], *, placeholder: str = ENTITY_PLACEHOLDER) -> str:
    """Replace every listed entity in ``text`` with ``placeholder``.

    Entities are matched longest-first so ``宁德时代新能源`` is redacted as one
    placeholder instead of leaving the tail of a shorter overlapping match
    behind. Runs of adjacent placeholders collapse into one.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    ordered = sorted({entity for entity in entities if entity}, key=len, reverse=True)
    if not ordered:
        return text
    pattern = re.compile("|".join(re.escape(entity) for entity in ordered), re.IGNORECASE)
    redacted = pattern.sub(placeholder, text)
    return _PLACEHOLDER_RUN_RE.sub(placeholder, redacted)


def redact_surfaces(surfaces: Mapping[str, str], entities: Iterable[str], *, placeholder: str = ENTITY_PLACEHOLDER) -> dict[str, str]:
    """Redact a mapping of field name → text, returning only the changed fields."""
    entity_list = tuple(entities)
    return {field: redact_entities(text, entity_list, placeholder=placeholder) for field, text in surfaces.items() if text}


def leaked_fields(surfaces: Mapping[str, str], entities: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Map each abstract surface to the entities it leaked, omitting clean ones."""
    entity_list = tuple(entities)
    leaked: dict[str, tuple[str, ...]] = {}
    for field, text in surfaces.items():
        found = find_leaked_entities(text, entity_list)
        if found:
            leaked[field] = found
    return leaked
